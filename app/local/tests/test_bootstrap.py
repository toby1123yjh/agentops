from contextlib import contextmanager
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy.exc import OperationalError
from sqlalchemy import create_mock_engine


@pytest.mark.parametrize('existing', [[], ['local_credentials']])
def test_postgres_schema_has_no_supabase_auth_dependency(monkeypatch, existing):
    from agentops import local_auth

    ddl = []
    engine = create_mock_engine('postgresql+psycopg://', lambda sql, *args, **kwargs: ddl.append(str(sql.compile(dialect=engine.dialect))))
    @contextmanager
    def begin():
        yield engine
    monkeypatch.setattr(local_auth, 'get_engine', lambda: SimpleNamespace(begin=begin))
    monkeypatch.setattr(local_auth, 'inspect', lambda conn: SimpleNamespace(get_table_names=lambda **kwargs: existing))
    monkeypatch.setenv('AGENTOPS_LOCAL_EMAIL', 'admin@test.invalid')
    monkeypatch.setenv('AGENTOPS_LOCAL_PASSWORD', 'test-password-only')
    added = []
    @contextmanager
    def session():
        yield SimpleNamespace(execute=lambda sql: None, scalar=lambda sql: uuid4() if existing else None, add=added.append, flush=lambda: None)
    monkeypatch.setattr(local_auth, 'session_scope', session)
    local_auth.bootstrap()
    statements = '\n'.join(ddl)
    assert 'CREATE TABLE public.local_credentials' in statements
    assert 'CREATE TABLE public.projects' in statements
    assert 'auth.users' not in statements
    if existing:
        assert added == []  # Restart never resets credentials or project/API keys.
    else:
        assert len(added) == 5
        credential = next(row for row in added if isinstance(row, local_auth.LocalCredential))
        assert credential.password_hash != 'test-password-only'


def test_postgres_rejects_unmarked_nonempty_database(monkeypatch):
    from agentops import local_auth
    @contextmanager
    def begin():
        yield SimpleNamespace(execute=lambda sql: None)
    monkeypatch.setattr(local_auth, 'get_engine', lambda: SimpleNamespace(begin=begin))
    monkeypatch.setattr(local_auth, 'inspect', lambda conn: SimpleNamespace(get_table_names=lambda **kwargs: ['users']))
    monkeypatch.setenv('AGENTOPS_LOCAL_EMAIL', 'admin@test.invalid')
    monkeypatch.setenv('AGENTOPS_LOCAL_PASSWORD', 'test-password-only')
    with pytest.raises(RuntimeError, match='empty dedicated database'):
        local_auth.bootstrap()


class ClickHouseRecorder:
    def __init__(self, tables=(), initialized=False, fail=False):
        self.tables, self.initialized, self.fail = tables, initialized, fail
        self.commands = []
        self.closed = False

    def query(self, sql):
        rows = [(table,) for table in self.tables] if sql.startswith('SHOW') else [(int(self.initialized),)]
        return SimpleNamespace(result_rows=rows)

    def command(self, sql):
        self.commands.append(sql)
        if self.fail and sql.startswith('CREATE TABLE IF NOT EXISTS otel_2.otel_logs'):
            raise RuntimeError('Simulated interrupted initialization')

    def close(self):
        self.closed = True


@pytest.mark.parametrize('tables,initialized', [((), False), (('local_schema_versions', 'otel_logs'), False), (('local_schema_versions',), True)])
def test_clickhouse_initialize_and_restart(monkeypatch, tables, initialized):
    from agentops import local_bootstrap
    client = ClickHouseRecorder(tables, initialized)
    monkeypatch.setattr(local_bootstrap, 'get_clickhouse', lambda: client)
    local_bootstrap.initialize_clickhouse()
    assert client.closed
    if initialized:
        assert len(client.commands) == 1  # Only IF NOT EXISTS marker DDL; no reseeding.
        return
    assert client.commands[-1] == 'INSERT INTO otel_2.local_schema_versions VALUES (1)'
    assert 'TRUNCATE TABLE otel_2.model_costs_source' in client.commands
    assert not any(sql.startswith('TRUNCATE TABLE otel_2.otel') for sql in client.commands)
    dictionary = next(sql for sql in client.commands if sql.startswith('CREATE DICTIONARY'))
    assert "SOURCE(CLICKHOUSE(DB 'otel_2'" in dictionary
    assert "USER 'default'" not in dictionary


def test_clickhouse_rejects_unmarked_database(monkeypatch):
    from agentops import local_bootstrap
    client = ClickHouseRecorder(('otel_traces',))
    monkeypatch.setattr(local_bootstrap, 'get_clickhouse', lambda: client)
    with pytest.raises(RuntimeError, match='empty dedicated database'):
        local_bootstrap.initialize_clickhouse()
    assert client.commands == [] and client.closed


def test_clickhouse_failure_never_marks_complete(monkeypatch):
    from agentops import local_bootstrap
    client = ClickHouseRecorder(fail=True)
    monkeypatch.setattr(local_bootstrap, 'get_clickhouse', lambda: client)
    with pytest.raises(RuntimeError, match='interrupted'):
        local_bootstrap.initialize_clickhouse()
    assert not any(sql.startswith('INSERT INTO otel_2.local_schema_versions') for sql in client.commands)
    assert client.closed


def test_postgres_initialization_retries_connection_failures(monkeypatch):
    from agentops import local_bootstrap
    calls = []

    def bootstrap():
        calls.append(True)
        if len(calls) == 1:
            raise OperationalError("connect", {}, RuntimeError("unavailable"))

    monkeypatch.setattr(local_bootstrap, "bootstrap", bootstrap)
    monkeypatch.setattr(local_bootstrap.time, "sleep", lambda _: None)
    monkeypatch.setenv("POSTGRES_CONNECT_ATTEMPTS", "2")
    monkeypatch.setenv("POSTGRES_CONNECT_DELAY_SECONDS", "0")
    local_bootstrap.initialize_postgres()
    assert len(calls) == 2
