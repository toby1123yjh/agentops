import os
import socket

os.environ.update({
    "AGENTOPS_LOCAL_MODE": "true",
    "AUTH_COOKIE_SECRET": "local-cookie-secret-for-tests-only-123456789",
    "JWT_SECRET_KEY": "local-jwt-secret-for-tests-only-123456789",
    "APP_DOMAIN": "localhost:32170",
    "API_DOMAIN": "localhost:32171",
    "PROTOCOL": "http",
    "GITHUB_ACTIONS": "true",
})

# Importing/testing the local app must not contact any hosted service.
def deny_network(*args, **kwargs):
    raise RuntimeError("Network access is disabled in local mode tests")

socket.create_connection = deny_network
