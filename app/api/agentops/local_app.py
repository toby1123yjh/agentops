"""Loopback-only local entry point reusing the original Dashboard APIs and permissions."""

from collections import deque
from threading import Lock
from time import monotonic

from agentops.common.local_mode import validate_local_settings

validate_local_settings()

from fastapi import APIRouter, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.middleware.trustedhost import TrustedHostMiddleware
from agentops.common.environment import APP_URL
from agentops.common.middleware import CacheControlMiddleware, ExceptionMiddleware
from agentops.auth.environment import AUTH_COOKIE_NAME, AUTH_COOKIE_EXPIRY
from agentops.auth.middleware import AuthenticatedRoute
from agentops.auth.schemas import LoginSchema
from agentops.auth.session import Session
from agentops.auth.views import _encode_session_cookie
from agentops.api.routes import v3, v4
from agentops.opsboard.app import app as opsboard_app
from agentops.local_auth import authenticate


app = FastAPI(title="AgentOps local", docs_url="/docs")
app.add_middleware(ExceptionMiddleware)
app.add_middleware(CacheControlMiddleware)
app.add_middleware(CORSMiddleware, allow_origins=[APP_URL], allow_credentials=True,
                   allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"], allow_headers=["*"])
app.add_middleware(TrustedHostMiddleware, allowed_hosts=["localhost", "127.0.0.1", "[::1]", "api"])

_attempts = deque()
_attempt_lock = Lock()


@app.middleware("http")
async def local_origin_guard(request: Request, call_next):
    # Local mode is authenticated, not an authentication bypass. Protect cookie mutations as well.
    origin = request.headers.get("origin")
    if origin and origin not in {APP_URL, str(request.base_url).rstrip("/")}:
        return JSONResponse({"detail": "Origin is not allowed in local mode"}, status_code=403)
    return await call_next(request)


@app.post("/auth/login")
def login(body: LoginSchema):
    now = monotonic()
    with _attempt_lock:
        while _attempts and _attempts[0] < now - 60:
            _attempts.popleft()
        if len(_attempts) >= 10:
            raise HTTPException(429, "Too many login attempts; retry in one minute")
        _attempts.append(now)
    user_id = authenticate(body.email, body.password)
    if not user_id:
        raise HTTPException(401, "Invalid email or password")
    response = JSONResponse({"success": True, "message": "Signed in locally"})
    response.set_cookie(AUTH_COOKIE_NAME, _encode_session_cookie(Session.create(user_id)),
                        httponly=True, secure=False, samesite="strict", path="/", max_age=AUTH_COOKIE_EXPIRY)
    return response


auth_router = APIRouter(route_class=AuthenticatedRoute)


@auth_router.post("/auth/logout")
def logout(request: Request):
    request.state.session.expire()
    response = JSONResponse({"success": True})
    response.delete_cookie(AUTH_COOKIE_NAME, path="/")
    return response


@app.get("/health")
def health():
    return {"mode": "local", "status": "up"}


app.include_router(auth_router)
app.include_router(v3.router)
app.include_router(v4.router)
app.mount("/opsboard", opsboard_app)
