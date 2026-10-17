"""FastAPI application factory entry point.

Used by:
  uvicorn pharma_next.main:application --factory
  docker CMD: uvicorn pharma_next.main:application --factory --host 0.0.0.0 --port 8000

Imports the API router from :mod:`pharma_next.api` and wires it to a
``CaseStore`` backed by ``PHARMA_DATABASE`` (default ``./data/cases.db``).
"""

from __future__ import annotations

import os

from .api import create_application

# Module-level application instance (uvicorn --factory calls this, or creates
# its own via create_application() when --factory is used).
application = create_application()

__all__ = ["application", "create_application"]
