"""Opt-in local configuration. Never infer local mode from the request host."""

import os
from urllib.parse import urlparse


LOCAL_MODE = os.getenv("AGENTOPS_LOCAL_MODE", "false").lower() == "true"


def validate_local_settings() -> None:
    if not LOCAL_MODE:
        raise RuntimeError("Set AGENTOPS_LOCAL_MODE=true to run the local server")
    for name in ("AUTH_COOKIE_SECRET", "JWT_SECRET_KEY"):
        value = os.getenv(name, "")
        if len(value) < 32 or value.startswith(("your_", "change-me", "super-secret")):
            raise RuntimeError(f"{name} must be a private random secret of at least 32 characters")
    for name, default in (("APP_DOMAIN", "localhost:3000"), ("API_DOMAIN", "localhost:8000")):
        host = urlparse("http://" + os.getenv(name, default)).hostname
        if host not in ("localhost", "127.0.0.1", "[::1]", "::1"):
            raise RuntimeError(f"{name} must be a loopback address in local mode")
    if os.getenv("PROTOCOL", "http") != "http":
        raise RuntimeError("Local mode is for loopback HTTP development, not public deployment")
