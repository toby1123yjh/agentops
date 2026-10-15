"""Cookie-authenticated project queries and separately JWT-authenticated SDK writes."""

import json
from datetime import datetime, timedelta, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import AwareDatetime, BaseModel, ValidationError
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from starlette.concurrency import run_in_threadpool

from agentops.api.auth import JWTPayload, get_jwt_token
from agentops.auth.middleware import AuthenticatedRoute
from agentops.common.orm import get_engine, get_orm_session, Session
from agentops.opsboard.models import ProjectModel
from .repository import SUMMARY, call_search, escape_like, ingest
from .schema import LIFECYCLES, OUTCOMES, TRANSITIONS, Observation

router = APIRouter(prefix='/tool-analysis/projects', route_class=AuthenticatedRoute)
ingest_router = APIRouter(prefix='/v1/tool-analysis')


def authorize(project_id: UUID, request: Request, orm: Session = Depends(get_orm_session)):
    project = ProjectModel.get_by_id(orm, str(project_id))
    if not project or not project.org.is_user_member(request.state.session.user_id):
        raise HTTPException(404, 'Project not found')
    return project_id


class Filters(BaseModel):
    start_time: AwareDatetime | None = None
    end_time: AwareDatetime | None = None
    agent_id: UUID | None = None
    model_id: str | None = None
    tool_type: str | None = None
    implementation_version: str | None = None


def scope(project_id, filters, source=None, tool=None, as_of=None):
    end = filters.end_time or datetime.now(timezone.utc)
    start = filters.start_time or end - timedelta(hours=24)
    if end <= start or end - start > timedelta(days=30):
        raise HTTPException(422, 'Time range must be positive and at most 30 days')
    where = 'project_id=:project AND requested_at>=:start AND requested_at<:end'
    params = {'project': project_id, 'start': start, 'end': end}
    for key, value in {
        'source_instance_id': source,
        'tool_key': tool,
        'agent_id': filters.agent_id,
        'model_id': filters.model_id,
        'tool_type': filters.tool_type,
        'implementation_version': filters.implementation_version,
    }.items():
        if value is not None:
            where += f' AND {key}=:{key}'
            params[key] = value
    if as_of:
        where += ' AND requested_at<=:as_of'
        params['as_of'] = as_of
    return where, params


def rows(conn, sql, params):
    return [dict(row) for row in conn.execute(text(sql), params).mappings()]


@ingest_router.post('/events')
async def receive(
    request: Request,
    payload: JWTPayload = Depends(get_jwt_token),
):
    # Stream with a limit rather than buffering an unbounded request body.
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > 1048576:
            raise HTTPException(413, 'Batch exceeds 1 MiB')
    try:
        data = json.loads(body)
        events = data['events']
        if not isinstance(events, list) or not 1 <= len(events) <= 50:
            raise ValueError()
    except (ValueError, KeyError, TypeError, RecursionError):
        raise HTTPException(422, 'Expected an events array of 1–50 observations')
    return await run_in_threadpool(receive_events, data, payload)


def receive_events(data, payload):
    # Own the synchronous ORM session in the worker that uses it.
    with Session(get_engine()) as orm:
        project = ProjectModel.get_by_id(orm, payload.project_id)
        if not project or str(project.api_key) != payload.api_key:
            raise HTTPException(401, 'Project key is no longer valid')
        project_id = project.id
    events = data['events']
    parsed = []
    for raw in events:
        try:
            if len(json.dumps(raw, ensure_ascii=False).encode()) > 65536:
                raise ValueError('event_too_large')
            parsed.append((raw, Observation.model_validate(raw)))
        except (ValidationError, ValueError, TypeError, RecursionError):
            parsed.append((raw, None))
    # Preflight the entire batch's source authorization before writing any event.
    with get_engine().begin() as conn:
        bindings = {str(event.source_instance_id): event for _, event in parsed if event is not None}
        for source in sorted(bindings):
            event = bindings[source]
            binding = conn.execute(
                text('''SELECT tenant_id FROM public.tool_analysis_sources
                WHERE project_id=:project AND source_instance_id=:source AND enabled FOR UPDATE'''),
                {'project': project_id, 'source': event.source_instance_id},
            ).first()
            if not binding or any(
                item.call.tenant_id != binding[0]
                for _, item in parsed
                if item and str(item.source_instance_id) == source
            ):
                raise HTTPException(403, 'Source is not bound to this project and tenant')
        receipts = []
        for raw, event in parsed:
            status = 'invalid'
            if event:
                try:
                    with conn.begin_nested():
                        status = ingest(conn, project_id, event)
                except PermissionError:
                    raise HTTPException(403, 'Source is not authorized')
                except IntegrityError:
                    status = 'conflict'
            receipts.append(
                {
                    'event_id': str(event.event_id)
                    if event
                    else (raw.get('event_id') if isinstance(raw, dict) else None),
                    'status': status,
                    'error_code': status if status in {'invalid', 'conflict', 'expired'} else None,
                }
            )
    return {'receipts': receipts}


@router.get('/{project_id}/tools')
def tools(
    project_id: UUID = Depends(authorize),
    filters: Filters = Depends(),
    q: str | None = Query(None, max_length=256),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    sort_by: str = 'request_count',
):
    order = {
        'request_count': 'request_count DESC',
        'known_success_rate': 'known_success_rate ASC NULLS LAST',
        'execution_p95_ms': 'execution_p95_ms DESC NULLS LAST',
    }.get(sort_by)
    if not order:
        raise HTTPException(422, 'Unsupported sort')
    where, params = scope(project_id, filters)
    if q:
        where += (
            " AND (tool_name ILIKE :q ESCAPE E'\\\\' OR tool_definition_id::text ILIKE :q ESCAPE E'\\\\')"
        )
        params['q'] = escape_like(q)
    grouped = f'''SELECT source_instance_id,tool_key,max(tool_definition_id::text) AS tool_definition_id,
        (array_agg(tool_name ORDER BY requested_at DESC))[1] AS tool_name,
        (array_agg(tool_type ORDER BY requested_at DESC))[1] AS tool_type,{SUMMARY}
        FROM public.tool_analysis_calls WHERE {where} GROUP BY source_instance_id,tool_key'''
    with get_engine().connect() as conn:
        total = conn.execute(text(f'SELECT count(*) FROM ({grouped}) grouped'), params).scalar()
        items = rows(
            conn,
            f'{grouped} ORDER BY {order},source_instance_id,tool_key LIMIT :limit OFFSET :offset',
            {**params, 'limit': limit, 'offset': offset},
        )
    return {'items': items, 'total': total, 'limit': limit, 'offset': offset}


@router.get('/{project_id}/filters')
def filter_options(
    project_id: UUID = Depends(authorize),
    filters: Filters = Depends(),
    source_instance_id: UUID | None = None,
    tool_key: str | None = None,
):
    # Do not restrict choices by the currently selected agent/model/type.
    window = Filters(start_time=filters.start_time, end_time=filters.end_time)
    where, params = scope(project_id, window, source_instance_id, tool_key)
    with get_engine().connect() as conn:
        agents = rows(
            conn,
            f'''SELECT agent_id AS value,max(snapshot->>'agent_name') AS label
            FROM public.tool_analysis_calls WHERE {where}
            AND agent_id IS NOT NULL GROUP BY agent_id ORDER BY label''',
            params,
        )
        models = rows(
            conn,
            f'''SELECT model_id AS value,max(snapshot->>'model_name') AS label
            FROM public.tool_analysis_calls WHERE {where}
            AND model_id IS NOT NULL GROUP BY model_id ORDER BY label''',
            params,
        )
        types = rows(
            conn,
            f'''SELECT DISTINCT tool_type AS value,tool_type AS label
            FROM public.tool_analysis_calls WHERE {where} ORDER BY tool_type''',
            params,
        )
    return {'agents': agents, 'models': models, 'types': types}


@router.get('/{project_id}/tools/{source_instance_id}/{tool_key}')
def detail(
    source_instance_id: UUID,
    tool_key: str,
    project_id: UUID = Depends(authorize),
    filters: Filters = Depends(),
):
    where, params = scope(project_id, filters, source_instance_id, tool_key)
    with get_engine().connect() as conn:
        latest = conn.execute(
            text(
                f'SELECT snapshot FROM public.tool_analysis_calls WHERE {where} '
                'ORDER BY requested_at DESC LIMIT 1'
            ),
            params,
        ).scalar()
        summary = rows(conn, f'SELECT {SUMMARY} FROM public.tool_analysis_calls WHERE {where}', params)[0]
        groups = rows(
            conn,
            f'''SELECT status_key,
            (array_agg(snapshot->'tool_status' ORDER BY source_updated_at DESC))[1] AS tool_status,
            implementation_version,execution_outcome,count(*) AS call_count,
            jsonb_build_object('verified_count',count(*) FILTER(WHERE status_verified),
              'unverified_count',count(*) FILTER(WHERE NOT status_verified),
              'conflict_count',count(*) FILTER(WHERE status_conflict),
              'kinds',jsonb_agg(DISTINCT snapshot->'status_evidence'->>'kind'),
              'adapter_versions',jsonb_agg(DISTINCT snapshot->'status_evidence'->>'adapter_version'))
              AS evidence_summary
            FROM public.tool_analysis_calls WHERE {where} AND execution_started IS TRUE
            GROUP BY status_key,implementation_version,execution_outcome
            ORDER BY call_count DESC,status_key''',
            params,
        )
        lifecycle = {
            row['code']: row['count']
            for row in rows(
                conn,
                f'''SELECT lifecycle_status AS code,count(*) AS count
            FROM public.tool_analysis_calls WHERE {where} GROUP BY lifecycle_status''',
                params,
            )
        }
        outcomes = {
            row['code']: row['count']
            for row in rows(
                conn,
                f'''SELECT execution_outcome AS code,count(*) AS count
            FROM public.tool_analysis_calls WHERE {where} GROUP BY execution_outcome''',
                params,
            )
        }
        versions = (
            conn.execute(
                text(
                    f'SELECT DISTINCT implementation_version FROM public.tool_analysis_calls WHERE {where} '
                    'ORDER BY implementation_version'
                ),
                params,
            )
            .scalars()
            .all()
        )
    total = summary['executed_call_count']
    for group in groups:
        group['ratio'] = group['call_count'] / total if total else None
    tool = {
        key: (latest or {}).get(key)
        for key in (
            'tool_name',
            'tool_definition_id',
            'tool_type',
            'description',
            'implementation_version',
            'executor_name',
            'tool_schema_hash',
        )
    }
    tool.update(source_instance_id=source_instance_id, tool_key=tool_key)
    tool['versions'] = versions
    return {
        'tool': tool,
        'summary': summary,
        'status_basis': 'latest_status_per_executed_call',
        'status_groups': groups,
        'as_of': datetime.now(timezone.utc),
        'lifecycle_summary': [
            {'code': code, 'label': label, 'count': lifecycle.get(code, 0)}
            for code, label in LIFECYCLES.items()
        ],
        'outcome_summary': [
            {'code': code, 'label': label, 'count': outcomes.get(code, 0)} for code, label in OUTCOMES.items()
        ],
        'transitions': TRANSITIONS,
    }


@router.get('/{project_id}/tools/{source_instance_id}/{tool_key}/calls')
def calls(
    source_instance_id: UUID,
    tool_key: str,
    project_id: UUID = Depends(authorize),
    filters: Filters = Depends(),
    search_field: str | None = None,
    search_value: str | None = Query(None, max_length=256),
    status_key: str | None = None,
    lifecycle_status: str | None = None,
    outcome: str | None = None,
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    as_of: AwareDatetime | None = None,
):
    as_of = as_of or datetime.now(timezone.utc)
    where, params = scope(project_id, filters, source_instance_id, tool_key, as_of)
    try:
        condition, search_params = call_search(search_field, search_value)
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    where += condition
    params.update(search_params)
    if status_key:
        where += ' AND status_key=:status_key AND execution_started IS TRUE'
        params['status_key'] = status_key
    for name, value, allowed in [
        ('lifecycle_status', lifecycle_status, LIFECYCLES),
        ('execution_outcome', outcome, OUTCOMES),
    ]:
        if value is not None:
            if value not in allowed:
                raise HTTPException(422, 'Unsupported state')
            where += f' AND {name}=:{name}'
            params[name] = value
    with get_engine().connect() as conn:
        total = conn.execute(
            text(f'SELECT count(*) FROM public.tool_analysis_calls WHERE {where}'), params
        ).scalar()
        items = rows(
            conn,
            f'''SELECT snapshot,revision,status_key FROM public.tool_analysis_calls WHERE {where}
            ORDER BY requested_at DESC,tool_call_id DESC LIMIT :limit OFFSET :offset''',
            {**params, 'limit': limit, 'offset': offset},
        )
    return {
        'items': [
            {**row['snapshot'], 'revision': row['revision'], 'status_key': row['status_key']} for row in items
        ],
        'total': total,
        'limit': limit,
        'offset': offset,
        'as_of': as_of,
    }


@router.get('/{project_id}/calls/{source_instance_id}/{tool_call_id}')
def call_detail(source_instance_id: UUID, tool_call_id: UUID, project_id: UUID = Depends(authorize)):
    params = {'project': project_id, 'source': source_instance_id, 'call': tool_call_id}
    where = 'project_id=:project AND source_instance_id=:source AND tool_call_id=:call'
    with get_engine().connect() as conn:
        row = (
            conn.execute(
                text(f'SELECT snapshot,revision FROM public.tool_analysis_calls WHERE {where}'), params
            )
            .mappings()
            .first()
        )
        if not row:
            raise HTTPException(404, 'Call not found')
        events = rows(
            conn,
            f'''SELECT event_id,revision,event_type,occurred_at,received_at
            FROM public.tool_analysis_events WHERE {where} ORDER BY revision''',
            params,
        )
    revisions = {event['revision'] for event in events}
    # Return intervals, not a potentially huge list up to an untrusted int64 revision.
    gaps, previous = [], 0
    for revision in sorted(revisions):
        if revision > previous + 1:
            gaps.append({'from': previous + 1, 'to': revision - 1})
        previous = revision
    return {**row['snapshot'], 'revision': row['revision'], 'events': events, 'revision_gaps': gaps}
