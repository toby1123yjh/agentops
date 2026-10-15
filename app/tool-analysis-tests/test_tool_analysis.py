"""Contract and PostgreSQL integration checks. Use only an explicitly supplied disposable DB."""

import copy
import os
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import create_engine, text

from agentops.tool_analysis import migrate, repository, views
from agentops.tool_analysis.schema import Call, Observation, normalize_call


def observation(source, **changes):
    stamp = datetime.now(timezone.utc)
    definition = uuid4()
    call = dict(
        tool_call_id=str(uuid4()),
        tool_definition_id=str(definition),
        tool_key=f'db:{definition}',
        tool_name='read_file',
        tool_type='builtin',
        implementation_version='core-tools/1',
        requested_at=(stamp - timedelta(seconds=2)).isoformat(),
        updated_at=stamp.isoformat(),
        terminal_at=stamp.isoformat(),
        lifecycle_status='completed',
        execution_outcome='success',
        execution_started=True,
        attempts=[],
        attempts_complete=False,
        status_evidence=dict(
            kind='structured_result', adapter_version='core-result/1', raw={'is_error': False}
        ),
        session_id=str(uuid4()),
        turn_id=str(uuid4()),
        agent_name='reader',
        result_summary='returned',
    )
    call.update(changes)
    return dict(
        schema_version=1,
        event_id=str(uuid4()),
        revision=1,
        event_type='attempt.finished',
        occurred_at=stamp.isoformat(),
        source_system='cestc-claw',
        source_instance_id=str(source),
        call=call,
    )


@pytest.fixture(scope='module')
def engine():
    url = os.environ.get('AGENTOPS_TOOL_TEST_DATABASE_URL')
    if not url:
        pytest.skip('Set AGENTOPS_TOOL_TEST_DATABASE_URL to a disposable PostgreSQL database')
    engine = create_engine(url, pool_size=1, max_overflow=0, connect_args={'prepare_threshold': None})
    with engine.begin() as conn:
        conn.execute(text('CREATE TABLE IF NOT EXISTS public.projects(id uuid PRIMARY KEY)'))
    original = migrate.get_engine
    migrate.get_engine = lambda: engine
    try:
        migrate.migrate()
        migrate.migrate()
    finally:
        migrate.get_engine = original
    yield engine
    engine.dispose()


@pytest.fixture()
def project(engine, monkeypatch):
    project_id, source = uuid4(), uuid4()
    with engine.begin() as conn:
        conn.execute(text('INSERT INTO public.projects(id) VALUES(:id)'), {'id': project_id})
        conn.execute(
            text("""INSERT INTO public.tool_analysis_sources
            (project_id,source_instance_id,source_system,name)
            VALUES(:project,:source,'cestc-claw','test')"""),
            {'project': project_id, 'source': source},
        )
    monkeypatch.setattr(views, 'get_engine', lambda: engine)
    return project_id, source


def test_late_duplicate_and_conflicting_revisions(engine, project):
    project_id, source = project
    terminal = observation(source)
    terminal['revision'] = 4
    early = copy.deepcopy(terminal)
    early.update(event_id=str(uuid4()), revision=1, event_type='call.requested')
    early['call'].update(
        lifecycle_status='requested', execution_outcome='pending', execution_started=False, terminal_at=None
    )
    with engine.begin() as conn:
        assert repository.ingest(conn, project_id, Observation.model_validate(terminal)) == 'accepted'
        assert repository.ingest(conn, project_id, Observation.model_validate(early)) == 'superseded'
        assert repository.ingest(conn, project_id, Observation.model_validate(terminal)) == 'duplicate'
        conflict = copy.deepcopy(terminal)
        conflict['call']['result_summary'] = 'changed'
        assert repository.ingest(conn, project_id, Observation.model_validate(conflict)) == 'conflict'
        conflict['event_id'] = str(uuid4())
        assert repository.ingest(conn, project_id, Observation.model_validate(conflict)) == 'conflict'
        row = conn.execute(
            text('SELECT revision,execution_outcome FROM public.tool_analysis_calls WHERE project_id=:p'),
            {'p': project_id},
        ).one()
        assert tuple(row) == (4, 'success')
    detail = views.detail(source, terminal['call']['tool_key'], project_id, views.Filters())
    assert detail['summary']['request_count'] == 1
    assert sum(item['count'] for item in detail['lifecycle_summary']) == 1
    assert next(item['count'] for item in detail['lifecycle_summary'] if item['code'] == 'completed') == 1
    call = views.call_detail(source, UUID(terminal['call']['tool_call_id']), project_id)
    assert call['revision_gaps'] == [{'from': 2, 'to': 3}]


def test_source_and_tenant_binding(engine, project):
    project_id, source = project
    raw = observation(source, tenant_id=str(uuid4()))
    with engine.begin() as conn:
        with pytest.raises(PermissionError):
            repository.ingest(conn, project_id, Observation.model_validate(raw))
        with pytest.raises(PermissionError):
            repository.ingest(conn, uuid4(), Observation.model_validate(observation(source)))


@pytest.mark.parametrize('field', ['session_id', 'turn_id', 'tool_call_id'])
def test_exact_identifier_search(engine, project, field):
    project_id, source = project
    raw = observation(source)
    with engine.begin() as conn:
        repository.ingest(conn, project_id, Observation.model_validate(raw))

    def query(value):
        return views.calls(
            source,
            raw['call']['tool_key'],
            project_id,
            views.Filters(),
            search_field=field,
            search_value=value,
            status_key=None,
            lifecycle_status=None,
            outcome=None,
            limit=50,
            offset=0,
            as_of=None,
        )

    assert query(raw['call'][field].upper())['total'] == 1
    assert query(raw['call'][field][:8])['total'] == 0
    wrong = raw['call']['turn_id' if field == 'session_id' else 'session_id']
    assert query(wrong)['total'] == 0


def test_literal_search_full_range_status_intersection_and_summary(engine, project):
    project_id, source = project
    raw = observation(source)
    key = raw['call']['tool_key']
    with engine.begin() as conn:
        for index in range(54):
            event = copy.deepcopy(raw)
            event.update(event_id=str(uuid4()))
            event['call'].update(
                tool_call_id=str(uuid4()),
                session_title='目标 100%_\\值' if index == 0 else '别的会话',
                agent_name='另一个字段',
                result_summary='普通结果',
                requested_at=(datetime.now(timezone.utc) - timedelta(seconds=120 - index)).isoformat(),
            )
            repository.ingest(conn, project_id, Observation.model_validate(event))

    def query(field, value, **states):
        return views.calls(
            source,
            key,
            project_id,
            views.Filters(),
            search_field=field,
            search_value=value,
            status_key=None,
            lifecycle_status=None,
            outcome=states.get('outcome'),
            limit=50,
            offset=0,
            as_of=None,
        )

    assert query('session_title', r'100%_\值')['total'] == 1
    assert query('result_summary', '100%')['total'] == 0
    assert query('session_title', '目标', outcome='failure')['total'] == 0
    assert views.detail(source, key, project_id, views.Filters())['summary']['request_count'] == 54


def test_mixed_results_and_execution_samples(engine, project):
    project_id, source = project
    events = [
        observation(source),
        observation(
            source,
            execution_outcome='failure',
            status_evidence=dict(
                kind='structured_result', adapter_version='core-result/1', raw={'is_error': True}
            ),
        ),
        observation(
            source,
            execution_outcome='unknown',
            status_evidence=dict(kind='string', adapter_version='legacy-string/1', raw={}),
        ),
        observation(
            source,
            lifecycle_status='awaiting_approval',
            execution_outcome='pending',
            execution_started=False,
            terminal_at=None,
        ),
    ]
    key = events[0]['call']['tool_key']
    with engine.begin() as conn:
        for event in events:
            event['call'].update(tool_key=key, tool_definition_id=events[0]['call']['tool_definition_id'])
            repository.ingest(conn, project_id, Observation.model_validate(event))
    result = views.detail(source, key, project_id, views.Filters())
    assert result['summary']['known_success_rate'] == 0.5
    assert result['summary']['execution_avg_ms'] is None
    assert result['summary']['executed_call_count'] == 3
    assert len(result['lifecycle_summary']) == 8 and len(result['outcome_summary']) == 6


@pytest.mark.parametrize(
    'changes',
    [
        {'model_return_chars': 2**63},
        {'execution_ms': float('nan')},
        {'attributes': {'bad': float('inf')}},
        {'result_summary': 'a\x00b'},
        {'lifecycle_status': 'running'},
        {'trace_id': '0' * 32},
    ],
)
def test_invalid_payloads_do_not_reach_postgres(changes):
    with pytest.raises((ValidationError, ValueError)):
        Call.model_validate(observation(uuid4(), **changes)['call'])


def test_evidence_never_promotes_a_string_or_conflicting_success():
    call = observation(
        uuid4(), status_evidence=dict(kind='text', adapter_version='legacy-string/1', verified=True, raw={})
    )['call']
    assert normalize_call(Call.model_validate(call))['execution_outcome'] == 'unknown'
    call['status_evidence'].update(adapter_version='core-result/1', raw={'is_error': False, 'exit_code': 7})
    result = normalize_call(Call.model_validate(call))
    assert result['execution_outcome'] == 'unknown' and result['status_evidence']['conflict']


def test_jwt_route_receipts_and_preflight_prevent_partial_cross_source_writes(engine, project, monkeypatch):
    project_id, source = project
    fake = SimpleNamespace(id=project_id, api_key='test-key')
    monkeypatch.setattr(
        views.ProjectModel,
        'get_by_id',
        lambda session, identity: fake if str(identity) == str(project_id) else None,
    )
    app = FastAPI()
    app.include_router(views.ingest_router)
    payload = SimpleNamespace(project_id=str(project_id), api_key='test-key')
    app.dependency_overrides[views.get_jwt_token] = lambda: payload
    client = TestClient(app)
    event = observation(source)
    response = client.post('/v1/tool-analysis/events', json={'events': [event, {'event_id': str(uuid4())}]})
    assert response.status_code == 200, response.text
    assert [item['status'] for item in response.json()['receipts']] == ['accepted', 'invalid']
    assert (
        client.post('/v1/tool-analysis/events', json={'events': [event]}).json()['receipts'][0]['status']
        == 'duplicate'
    )
    second = observation(source)
    bad = observation(uuid4())
    assert client.post('/v1/tool-analysis/events', json={'events': [second, bad]}).status_code == 403
    with engine.connect() as conn:
        assert (
            conn.execute(
                text('SELECT count(*) FROM public.tool_analysis_calls WHERE project_id=:p'), {'p': project_id}
            ).scalar()
            == 1
        )
    assert client.post('/v1/tool-analysis/events', content=b'x' * 1048577).status_code == 413
    app.dependency_overrides.clear()
    assert client.post('/v1/tool-analysis/events', json={'events': [event]}).status_code == 401


def test_cestc_claw_emitted_snapshots_match_ingestion_contract(engine, project):
    project_id, _ = project
    with engine.begin() as conn:
        if not conn.execute(text("SELECT to_regclass('public.tool_telemetry_outbox')")).scalar():
            pytest.skip(
                'Run the source PostgreSQL tests in the same disposable DB to verify the wire contract'
            )
        emitted = (
            conn.execute(
                text('SELECT envelope FROM public.tool_telemetry_outbox ORDER BY created_at,revision')
            )
            .scalars()
            .all()
        )
        assert emitted
        for envelope in emitted:
            event = Observation.model_validate(envelope)
            conn.execute(
                text("""INSERT INTO public.tool_analysis_sources
                (project_id,source_instance_id,source_system,name)
                VALUES(:p,:s,'cestc-claw','source integration') ON CONFLICT DO NOTHING"""),
                {'p': project_id, 's': event.source_instance_id},
            )
            assert repository.ingest(conn, project_id, event) in {'accepted', 'superseded'}
        completed = (
            conn.execute(
                text("""SELECT snapshot FROM public.tool_analysis_calls
            WHERE project_id=:p AND execution_outcome='success'"""),
                {'p': project_id},
            )
            .scalars()
            .all()
        )
        assert any(call['model_return_chars'] == 2 and call['model_return_bytes'] == 6 for call in completed)
