import os
from urllib.parse import urlparse
from .local_mode import LOCAL_MODE, get_public_url

# Base URLs and domains
PUBLIC_URL = get_public_url() if LOCAL_MODE else None
if PUBLIC_URL:
    _public = urlparse(PUBLIC_URL)
    APP_DOMAIN = _public.netloc
    API_DOMAIN = _public.netloc
    PROTOCOL = _public.scheme
else:
    APP_DOMAIN = os.getenv("APP_DOMAIN", "localhost:3000" if LOCAL_MODE else "app.agentops.ai")
    API_DOMAIN = os.getenv("API_DOMAIN", "localhost:8000" if LOCAL_MODE else "api.agentops.ai")
    # Protocol defaults to HTTPS in cloud mode and loopback HTTP in local mode.
    PROTOCOL = os.getenv("PROTOCOL", "http" if LOCAL_MODE else "https")

# Full base URLs
APP_URL = f"{PROTOCOL}://{APP_DOMAIN}"
API_URL = f"{PROTOCOL}://{API_DOMAIN}"

# Common application URLs
DASHBOARD_URL = f"{APP_URL}/projects"
LOGIN_URL = f"{APP_URL}/login"

# CORS Configuration
ALLOWED_ORIGINS = [
    APP_URL,
]


SQLALCHEMY_LOG_LEVEL = os.environ.get("SQLALCHEMY_LOG_LEVEL")


SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

# Supabase Postgres connection details
SUPABASE_HOST = os.getenv('SUPABASE_HOST')
SUPABASE_PORT = os.getenv('SUPABASE_PORT')
SUPABASE_DATABASE = os.getenv('SUPABASE_DATABASE')
SUPABASE_USER = os.getenv('SUPABASE_USER')
SUPABASE_PASSWORD = os.getenv('SUPABASE_PASSWORD')
SUPABASE_SSLMODE = os.getenv('SUPABASE_SSLMODE', 'prefer')

# Plain PostgreSQL in local mode; cloud configuration remains unchanged.
if LOCAL_MODE:
    SUPABASE_HOST = os.getenv("POSTGRES_HOST", "localhost")
    SUPABASE_PORT = os.getenv("POSTGRES_PORT", "5432")
    SUPABASE_DATABASE = os.getenv("POSTGRES_DB", "agentops_local")
    SUPABASE_USER = os.getenv("POSTGRES_USER", "agentops")
    SUPABASE_PASSWORD = os.getenv("POSTGRES_PASSWORD")
    SUPABASE_SSLMODE = os.getenv("POSTGRES_SSLMODE", "disable")

# Supabase allows up to 20 pool connections and 1000 max connections.
# Since we share connections with other instances (dev, staging) these defaults
# are kept low and are expected to be overridden in production.
# pool sizes are referenced *both* for the direct psycopg connection pool and
# the SQLAlchemy connection pool (so in practice they are doubled)
SUPABASE_MIN_POOL_SIZE: int = int(os.getenv('SUPABASE_MIN_POOL_SIZE', 1))
SUPABASE_MAX_POOL_SIZE: int = int(os.getenv('SUPABASE_MAX_POOL_SIZE', 10))

# you can see the max pool size with (observed to be 240):
# SELECT name, setting
# FROM pg_settings
# WHERE name IN ('max_connections', 'superuser_reserved_connections');

# you can see active connections with:
# SELECT count(*) AS total, state, usename, backend_type
# FROM pg_stat_activity
# GROUP BY state, usename, backend_type;


REDIS_HOST = os.getenv('REDIS_HOST')
REDIS_PORT = os.getenv('REDIS_PORT')
REDIS_USER = os.getenv('REDIS_USER')
REDIS_PASSWORD = os.getenv('REDIS_PASSWORD')


# enable rate limiting on public endpoints (default: false)
RATE_LIMIT_ENABLE: bool = os.getenv("RATE_LIMIT_ENABLE", "false").lower() == "true"
# Window time for counting rate limited requests
RATE_LIMIT_WINDOW: int = int(os.getenv("RATE_LIMIT_WINDOW", 60))  # 60 seconds (1 minute)
# Maximum allowed requests within the window
RATE_LIMIT_COUNT: int = int(os.getenv("RATE_LIMIT_COUNT", 6))  # 6 requests per minute
# How long to keep the rate limit key in cache after exceeding limits
RATE_LIMIT_EXPIRY: int = int(os.getenv("RATE_LIMIT_EXPIRY", 60 * 60))  # 1 hour


# number of users to allow for free users
FREEPLAN_MAX_USERS: int = int(os.getenv('FREEPLAN_MAX_USERS', 1))
# # number or orgs to allow for free users
# TODO since freeplan is at the org level do we only allow a user to belong to one org?
# FREEPLAN_MAX_ORGS = int(os.getenv('FREEPLAN_MAX_ORGS', 1))
# number of projects to allow for free users
FREEPLAN_MAX_PROJECTS: int = int(os.getenv('FREEPLAN_MAX_PROJECTS', 1))

# number of days we allow access to metrics data for free users
FREEPLAN_METRICS_DAYS_CUTOFF: int = int(os.getenv('FREEPLAN_METRICS_DAYS_CUTOFF', 30))

# number of days to allow access to traces for free users
FREEPLAN_TRACE_DAYS_CUTOFF: int = int(os.getenv('FREEPLAN_TRACE_DAYS_CUTOFF', 3))
# minimum number of traces to include in a trace view
FREEPLAN_TRACE_MIN_NUM: int = int(os.getenv('FREEPLAN_TRACE_MIN_NUM', 3))
# number of spans to include the full contents of in a trace detail view
FREEPLAN_SPANS_LIST_LIMIT: int = int(os.getenv('FREEPLAN_SPANS_LIST_LIMIT', 30))

# number of lines to show in the logs for free users
FREEPLAN_LOGS_LINE_LIMIT: int = int(os.getenv('FREEPLAN_LOGS_LINE_LIMIT', 100))

# TODO 10,000 spans per month is not enforced.

# GitHub Oauth
GITHUB_CLIENT_ID = os.environ.get("GITHUB_OAUTH_CLIENT_ID")
GITHUB_CLIENT_SECRET = os.environ.get("GITHUB_OAUTH_CLIENT_SECRET")
