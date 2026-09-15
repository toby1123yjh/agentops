from fastapi import APIRouter

from agentops.common.route_config import RouteConfig, register_routes
from agentops.auth.middleware import AuthenticatedRoute
from agentops.common.local_mode import LOCAL_MODE

from .metrics.views import ProjectMetricsView
from .traces.views import TraceListView, TraceDetailView
from .logs import LogsUploadView, get_trace_logs
from .objects import ObjectUploadView

from agentops.api.routes.v4.stripe_webhooks import router as stripe_webhooks_router

__all__ = ["router"]


router = APIRouter(prefix="/v4")


route_config: list[RouteConfig] = [
    # Metrics
    RouteConfig(
        name='get_project_metrics',
        path="/meterics/project/{project_id}",
        endpoint=ProjectMetricsView,
        methods=["GET"],
    ),
    # Traces
    RouteConfig(
        name='get_project_traces',
        path="/traces/list/{project_id}",
        endpoint=TraceListView,
        methods=["GET"],
    ),
    RouteConfig(
        name='get_trace',
        path="/traces/detail/{trace_id}",
        endpoint=TraceDetailView,
        methods=["GET"],
    ),
    # Objects
    RouteConfig(
        name='upload_object',
        path="/objects/upload/",
        endpoint=ObjectUploadView,
        methods=["POST"],
    ),
    # Logs
    RouteConfig(
        name='upload_logs',
        path="/logs/upload/",
        endpoint=LogsUploadView,
        methods=["POST"],
    ),
    RouteConfig(
        name='get_trace_logs',
        path="/logs/{trace_id}",
        endpoint=get_trace_logs,
        methods=["GET"],
    ),
]

api_router = APIRouter(route_class=AuthenticatedRoute)
if LOCAL_MODE:
    route_config = [route for route in route_config if route.name in {
        "get_project_metrics", "get_project_traces", "get_trace",
    }]
register_routes(api_router, route_config, prefix="/v4")
router.include_router(api_router)

if not LOCAL_MODE:
    router.include_router(stripe_webhooks_router)
