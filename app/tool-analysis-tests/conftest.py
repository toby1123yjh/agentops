import os
from pathlib import Path
import sys

# This repository also contains an SDK named agentops. Test the API package explicitly.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'api'))
os.environ.update(
    {
        'AGENTOPS_LOCAL_MODE': 'true',
        'JWT_SECRET_KEY': 'tool-analysis-test-only-01234567890123456789',
        'AUTH_COOKIE_SECRET': 'tool-analysis-cookie-test-only-0123456789',
        'GITHUB_ACTIONS': 'true',
    }
)
