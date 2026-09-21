"""Explicit self-hosted configuration. Never infer the mode from a request host."""

import os
from urllib.parse import urlparse


LOCAL_MODE = os.getenv("AGENTOPS_LOCAL_MODE", "false").lower() == "true"


def get_public_url() -> str | None:
    """Return a validated, normalized self-hosted URL when one is configured."""
    value = os.getenv("AGENTOPS_PUBLIC_URL", "").strip().rstrip("/")
    if not value:
        return None
    parsed = urlparse(value)
    if (
        parsed.scheme not in ("http", "https")
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.path
        or parsed.params
        or parsed.query
        or parsed.fragment
    ):
        raise RuntimeError(
            "AGENTOPS_PUBLIC_URL must be an http(s) origin without a path, query, or credentials"
        )
    return value


def validate_local_settings() -> None:
    if not LOCAL_MODE:
        raise RuntimeError("Set AGENTOPS_LOCAL_MODE=true to run the local server")
    for name in ("AUTH_COOKIE_SECRET", "JWT_SECRET_KEY"):
        value = os.getenv(name, "")
        if len(value) < 32 or value.startswith(("your_", "change-me", "super-secret")):
            raise RuntimeError(f"{name} must be a private random secret of at least 32 characters")
    if get_public_url():
        return
    for name, default in (("APP_DOMAIN", "localhost:3000"), ("API_DOMAIN", "localhost:8000")):
        host = urlparse("http://" + os.getenv(name, default)).hostname
        if host not in ("localhost", "127.0.0.1", "[::1]", "::1"):
            raise RuntimeError(f"{name} must be a loopback address in local mode")
    if os.getenv("PROTOCOL", "http") != "http":
        raise RuntimeError("Local mode is for loopback HTTP development, not public deployment")
