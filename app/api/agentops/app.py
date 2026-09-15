"""Select the backend mode explicitly; cloud behavior remains the default."""

from agentops.common.local_mode import LOCAL_MODE

if LOCAL_MODE:
    from agentops.local_app import app
else:
    from agentops.cloud_app import app

__all__ = ["app"]
