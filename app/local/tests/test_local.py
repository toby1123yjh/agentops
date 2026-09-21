from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
import yaml
from fastapi.testclient import TestClient
from werkzeug.security import generate_password_hash

from agentops.common.local_mode import validate_local_settings


@pytest.fixture
def client(monkeypatch):
    from agentops import local_app, local_auth
    user_id = uuid4()
    sessions = {}
    monkeypatch.setattr(local_app, "authenticate", lambda email, password: user_id if (email, password) == ("local@test.invalid", "correct-password") else None)
    monkeypatch.setattr(local_auth, "create_session", lambda sid, uid, ttl: sessions.update({str(sid): uid}))
    monkeypatch.setattr(local_auth, "get_session_user", lambda sid: sessions.get(str(sid)))
    monkeypatch.setattr(local_auth, "update_session", lambda sid, ttl: sessions.pop(str(sid), None) if ttl is None else None)
    local_app._attempts.clear()
    with TestClient(local_app.app, base_url="http://localhost:32171") as test_client:
        yield test_client


def test_settings_require_private_secrets(monkeypatch):
    validate_local_settings()
    monkeypatch.setenv("AUTH_COOKIE_SECRET", "change-me")
    with pytest.raises(RuntimeError, match="AUTH_COOKIE_SECRET"):
        validate_local_settings()


def test_settings_reject_public_host(monkeypatch):
    monkeypatch.setenv("APP_DOMAIN", "example.com")
    with pytest.raises(RuntimeError, match="loopback"):
        validate_local_settings()


@pytest.mark.parametrize("url", ["http://agentops-dev.example.test", "https://agentops.example.test"])
def test_settings_accept_explicit_public_origin(monkeypatch, url):
    monkeypatch.setenv("AGENTOPS_PUBLIC_URL", url)
    validate_local_settings()


@pytest.mark.parametrize("url", [
    "agentops.example.test",
    "ftp://agentops.example.test",
    "https://user:password@agentops.example.test",
    "https://agentops.example.test/path",
    "https://agentops.example.test?query=1",
])
def test_settings_reject_invalid_public_origin(monkeypatch, url):
    monkeypatch.setenv("AGENTOPS_PUBLIC_URL", url)
    with pytest.raises(RuntimeError, match="AGENTOPS_PUBLIC_URL"):
        validate_local_settings()


def test_mode_is_explicit(monkeypatch):
    import agentops.common.local_mode as settings
    monkeypatch.setattr(settings, 'LOCAL_MODE', False)
    with pytest.raises(RuntimeError, match="AGENTOPS_LOCAL_MODE"):
        validate_local_settings()


def test_unauthed_project_access_is_rejected(client):
    assert client.get('/opsboard/projects').status_code == 401


def test_login_cookie_and_logout(client):
    bad = client.post('/auth/login', json={'email': 'local@test.invalid', 'password': 'wrong'})
    assert bad.status_code == 401
    response = client.post('/auth/login', json={'email': 'local@test.invalid', 'password': 'correct-password'})
    assert response.status_code == 200
    cookie = response.headers['set-cookie'].lower()
    assert 'httponly' in cookie and 'samesite=strict' in cookie
    assert 'domain=' not in cookie
    assert 'correct-password' not in response.text
    assert client.post('/auth/logout').status_code == 200
    assert client.post('/auth/logout').status_code == 401


@pytest.mark.parametrize('path', ['/auth/signup', '/auth/oauth', '/auth/session', '/v1/sessions', '/v4/objects/upload/', '/v4/logs/upload/', '/deploy'])
def test_cloud_routes_are_not_mounted(client, path):
    assert client.post(path, json={}).status_code == 404


def test_csrf_and_host_guard(client):
    assert client.post('/auth/login', headers={'origin': 'https://evil.invalid'}, json={}).status_code == 403
    assert client.get('/health', headers={'host': 'evil.invalid'}).status_code == 400
    assert client.get('/health').json()['mode'] == 'local'


def test_rate_limit(client):
    for _ in range(10):
        assert client.post('/auth/login', json={'email': 'local@test.invalid', 'password': 'wrong'}).status_code == 401
    assert client.post('/auth/login', json={'email': 'local@test.invalid', 'password': 'wrong'}).status_code == 429


def test_authentication_uses_hash(monkeypatch):
    from agentops import local_auth
    user_id = uuid4()
    credential = SimpleNamespace(user_id=user_id, password_hash=generate_password_hash('correct-password'))
    @contextmanager
    def fake_session():
        yield SimpleNamespace(scalar=lambda query: credential)
    monkeypatch.setattr(local_auth, 'session_scope', fake_session)
    assert local_auth.authenticate('local@test.invalid', 'correct-password') == user_id
    assert local_auth.authenticate('local@test.invalid', 'wrong') is None


def test_expired_session_not_renewed(monkeypatch):
    from agentops import local_auth
    session_id = uuid4()
    expired = datetime.now(timezone.utc) - timedelta(seconds=1)
    row = SimpleNamespace(user_id=uuid4(), expires_at=expired)
    @contextmanager
    def fake_session():
        yield SimpleNamespace(get=lambda *args: row)
    monkeypatch.setattr(local_auth, 'session_scope', fake_session)
    assert local_auth.get_session_user(session_id) is None
    local_auth.update_session(session_id, 3600)
    assert row.expires_at == expired
    assert local_auth.get_session_user('malformed') is None


def test_local_compose_is_isolated():
    root = Path(__file__).resolve().parents[2]
    compose = yaml.safe_load((root / 'compose.local.yaml').read_text(encoding='utf-8'))
    assert 'supabase' not in compose['services']
    for name, service in compose['services'].items():
        assert service.get('network_mode') != 'host'
        for port in service.get('ports', []):
            assert port.startswith('127.0.0.1:')
        build = service.get('build')
        if build:
            assert (root / build['context'] / build['dockerfile']).resolve().is_file()
    assert compose['services']['api']['depends_on']['initialize']['condition'] == 'service_completed_successfully'
    assert compose['services']['dashboard']['ports'] == ['127.0.0.1:${AGENTOPS_DASHBOARD_PORT:-32170}:3000']
    assert compose['services']['api']['ports'] == ['127.0.0.1:${AGENTOPS_API_PORT:-32171}:8000']
    assert compose['services']['otelcollector']['ports'] == ['127.0.0.1:${AGENTOPS_OTLP_PORT:-32172}:4318']
    assert len(compose['volumes']) == 2


def test_server_compose_uses_external_postgres():
    root = Path(__file__).resolve().parents[2]
    compose = yaml.safe_load((root / 'compose.server.yaml').read_text(encoding='utf-8'))
    assert 'postgres' not in compose['services']
    assert compose['networks']['database']['external'] is True
    assert compose['networks']['database']['name'] == '${AGENTOPS_DB_NETWORK:?Set AGENTOPS_DB_NETWORK}'
    for service_name in ('initialize', 'api'):
        assert 'database' in compose['services'][service_name]['networks']
    environment = compose['services']['api']['environment']
    assert environment['POSTGRES_HOST'] == '${POSTGRES_HOST:?Set POSTGRES_HOST}'
    assert environment['POSTGRES_DB'] == '${POSTGRES_DB:-agentops}'
    assert compose['services']['dashboard']['build']['args']['NEXT_PUBLIC_API_URL'] == (
        '${AGENTOPS_PUBLIC_URL:?Set AGENTOPS_PUBLIC_URL}'
    )
    assert list(compose['volumes']) == ['server-clickhouse']


def test_bootstrap_rejects_weak_password(monkeypatch):
    from agentops.local_auth import bootstrap
    monkeypatch.setenv('AGENTOPS_LOCAL_EMAIL', 'admin@localhost.test')
    monkeypatch.setenv('AGENTOPS_LOCAL_PASSWORD', 'short')
    with pytest.raises(RuntimeError, match='12 characters'):
        bootstrap()
