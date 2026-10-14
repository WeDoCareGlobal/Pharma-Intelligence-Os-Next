import json
import os
from pharma_next.api import create_app, Identity


def application():
    # Credentials are injected by the operator; never committed or logged.
    data = json.loads(os.environ['PHARMA_SERVICE_IDENTITIES'])
    identities = {token: Identity(**claims) for token, claims in data.items()}
    return create_app(os.environ.get('PHARMA_DATABASE', '/data/cases.db'), identities)
