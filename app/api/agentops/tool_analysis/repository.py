"""PostgreSQL ingestion, deduplication and project-scoped queries."""

import hashlib
from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import text

from .schema import Observation, canonical, normalize_call, status_key

IDENTITY = ('tool_key', 'tool_definition_id', 'requested_at', 'session_id', 'turn_id', 'provider_round_id')
PROJECTIONS = (
    'tool_key',
    'tool_definition_id',
    'tool_name',
    'tool_type',
    'implementation_version',
    'agent_id',
    'model_id',
    'session_id',
    'turn_id',
    'provider_round_id',
    'lifecycle_status',
    'execution_outcome',
    'execution_started',
    'execution_ms',
    'dispatch_ms',
    'attempts_complete',
    'model_return_chars',
    'output_truncated',
)
SEARCH_FIELDS = {
    'tool_call_id': 'tool_call_id',
    'session_id': 'session_id',
    'turn_id': 'turn_id',
    'session_title': "snapshot->>'session_title'",
    'turn_input_preview': "snapshot->>'turn_input_preview'",
    'agent_name': "snapshot->>'agent_name'",
    'result_summary': "snapshot->>'result_summary'",
}


def ingest(conn, project_id: UUID, event: Observation) -> str:
    raw = event.model_dump(mode='json')
    source, call_id = event.source_instance_id, event.call.tool_call_id
    scope = {'project': project_id, 'source': source, 'call': call_id}
    # Serialize a source's small batch; also protects duplicate event IDs targeting different calls.
    binding = (
        conn.execute(
            text('''SELECT tenant_id,enabled FROM public.tool_analysis_sources
        WHERE project_id=:project AND source_instance_id=:source FOR UPDATE'''),
            scope,
        )
        .mappings()
        .first()
    )
    if not binding or not binding['enabled'] or binding['tenant_id'] != event.call.tenant_id:
        raise PermissionError('source_not_authorized')
    conn.execute(
        text('''DELETE FROM public.tool_analysis_calls WHERE project_id=:project
        AND source_instance_id=:source AND requested_at<:cutoff'''),
        {**scope, 'cutoff': datetime.now(timezone.utc) - timedelta(days=30)},
    )
    if event.call.requested_at < datetime.now(timezone.utc) - timedelta(days=30):
        return 'expired'
    if event.call.requested_at > datetime.now(timezone.utc) + timedelta(minutes=5):
        return 'invalid'
    digest = hashlib.sha256(canonical(raw).encode()).hexdigest()
    previous = conn.execute(
        text('''SELECT payload_sha256 FROM public.tool_analysis_events
        WHERE project_id=:project AND source_instance_id=:source AND event_id=:event'''),
        {**scope, 'event': event.event_id},
    ).scalar()
    if previous:
        return 'duplicate' if previous == digest else 'conflict'
    old = (
        conn.execute(
            text('''SELECT revision,snapshot FROM public.tool_analysis_calls
        WHERE project_id=:project AND source_instance_id=:source AND tool_call_id=:call FOR UPDATE'''),
            scope,
        )
        .mappings()
        .first()
    )
    snapshot = normalize_call(event.call)
    snapshot_key = status_key(str(source), snapshot)
    del snapshot['_status_identity']
    if old:
        # Compare parsed instants, not equivalent RFC3339 spellings.
        for key in IDENTITY:
            a, b = old['snapshot'].get(key), snapshot.get(key)
            if key == 'requested_at':
                a, b = datetime.fromisoformat(a.replace('Z', '+00:00')), event.call.requested_at
            if a != b:
                return 'conflict'
        if (
            event.revision > old['revision']
            and old['snapshot']['lifecycle_status'] in {'completed', 'rejected', 'cancelled', 'interrupted'}
            and snapshot['lifecycle_status'] != old['snapshot']['lifecycle_status']
        ):
            return 'conflict'
        if conn.execute(
            text('''SELECT 1 FROM public.tool_analysis_events WHERE project_id=:project
            AND source_instance_id=:source AND tool_call_id=:call AND revision=:revision'''),
            {**scope, 'revision': event.revision},
        ).scalar():
            return 'conflict'
    values = {key: snapshot.get(key) for key in PROJECTIONS}
    values.update(
        scope,
        revision=event.revision,
        requested_at=event.call.requested_at,
        updated_at=event.call.updated_at,
        verified=snapshot['status_evidence']['verified'],
        conflict=snapshot['status_evidence']['conflict'],
        status_key=snapshot_key,
        snapshot=canonical(snapshot),
    )
    if not old:
        names = ','.join(PROJECTIONS)
        placeholders = ','.join(':' + key for key in PROJECTIONS)
        conn.execute(
            text(f'''INSERT INTO public.tool_analysis_calls
            (project_id,source_instance_id,tool_call_id,revision,requested_at,source_updated_at,
             status_verified,status_conflict,status_key,snapshot,{names})
            VALUES(:project,:source,:call,:revision,:requested_at,:updated_at,:verified,:conflict,
                   :status_key,CAST(:snapshot AS jsonb),{placeholders})'''),
            values,
        )
    elif event.revision > old['revision']:
        assignments = ','.join(f'{key}=:{key}' for key in PROJECTIONS)
        conn.execute(
            text(f'''UPDATE public.tool_analysis_calls SET {assignments},revision=:revision,
            source_updated_at=:updated_at,received_at=now(),status_verified=:verified,
            status_conflict=:conflict,status_key=:status_key,snapshot=CAST(:snapshot AS jsonb)
            WHERE project_id=:project AND source_instance_id=:source AND tool_call_id=:call'''),
            values,
        )
    conn.execute(
        text('''INSERT INTO public.tool_analysis_events
        (project_id,source_instance_id,event_id,tool_call_id,revision,event_type,occurred_at,payload_sha256,envelope)
        VALUES(:project,:source,:event,:call,:revision,:type,:at,:hash,CAST(:body AS jsonb))'''),
        {
            **scope,
            'event': event.event_id,
            'revision': event.revision,
            'type': event.event_type,
            'at': event.occurred_at,
            'hash': digest,
            'body': canonical(raw),
        },
    )
    return 'superseded' if old and event.revision < old['revision'] else 'accepted'


SUMMARY = '''count(*) AS request_count,
 count(*) FILTER(WHERE execution_started IS TRUE) AS executed_call_count,
 count(*) FILTER(WHERE execution_started IS FALSE) AS not_executed_call_count,
 count(*) FILTER(WHERE execution_started IS NULL) AS execution_unknown_count,
 count(*) FILTER(WHERE execution_outcome='unknown') AS unknown_count,
 count(*) FILTER(WHERE execution_outcome='pending') AS pending_count,
 count(*) FILTER(WHERE status_verified AND execution_outcome='success' AND execution_started IS TRUE)::float /
 NULLIF(count(*) FILTER(WHERE status_verified AND execution_started IS TRUE
   AND execution_outcome IN ('success','failure')),0) AS known_success_rate,
 count(*) FILTER(WHERE status_verified
   AND execution_outcome IN ('success','failure','rejected','cancelled'))::float
   / NULLIF(count(*),0) AS terminal_status_coverage,
 count(DISTINCT agent_id) AS agent_count,
 count(*) FILTER(WHERE status_verified AND execution_outcome='rejected'
   AND snapshot->>'error_stage'='validation') AS validation_rejected_count,
 count(*) FILTER(WHERE status_verified AND execution_outcome='rejected'
   AND snapshot->>'error_stage'='authorization') AS authorization_rejected_count,
 count(*) FILTER(WHERE status_verified AND execution_started IS TRUE
   AND execution_outcome='failure') AS execution_failure_count,
 count(*) FILTER(WHERE execution_ms IS NOT NULL AND attempts_complete AND status_verified
   AND execution_outcome IN ('success','failure')) AS execution_sample_count,
 avg(execution_ms) FILTER(WHERE attempts_complete AND status_verified
   AND execution_outcome IN ('success','failure')) AS execution_avg_ms,
 percentile_cont(0.95) WITHIN GROUP(ORDER BY execution_ms)
   FILTER(WHERE attempts_complete AND status_verified
   AND execution_outcome IN ('success','failure')) AS execution_p95_ms,
 avg(dispatch_ms) AS dispatch_avg_ms,
 count(*) FILTER(WHERE snapshot->>'retry_of_call_id' IS NOT NULL
   OR jsonb_array_length(snapshot->'attempts')>1) AS observed_retry_call_count,
 count(*) FILTER(WHERE attempts_complete) AS retry_covered_call_count,
 NULL::bigint AS duplicate_candidate_count,
 percentile_cont(0.5) WITHIN GROUP(ORDER BY model_return_chars) AS model_return_median_chars,
 count(model_return_chars) AS model_return_sample_count,
 count(*) FILTER(WHERE output_truncated IS TRUE)::float
   / NULLIF(count(output_truncated),0) AS truncation_rate,
 count(output_truncated) AS truncation_sample_count'''


def escape_like(value):
    return '%' + value.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_') + '%'


def call_search(field, value):
    if field is not None and field not in SEARCH_FIELDS:
        raise ValueError('unsupported_search_field')
    value = (value or '').strip()
    if not value:
        return '', {}
    if field is None:
        raise ValueError('search_field_required')
    column = SEARCH_FIELDS[field]
    if field.endswith('_id'):
        try:
            value = UUID(value)
        except ValueError:
            return ' AND FALSE', {}
        return f' AND {column}=:search_value', {'search_value': value}
    return f" AND {column} ILIKE :search_value ESCAPE E'\\\\'", {'search_value': escape_like(value)}
