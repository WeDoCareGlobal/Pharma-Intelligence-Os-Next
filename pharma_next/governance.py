"""Governance integration for Pharma Intelligence OS.

Inspects case content through OmniGuard before case operations.
Fail-closed: any error or non-ALLOW decision blocks the operation.
"""
import os
import logging
from typing import Optional

import httpx

logger = logging.getLogger(__name__)


class GovernanceError(Exception):
    """Raised when governance inspection fails or blocks."""
    pass


class OmniGuardGovernance:
    """Fail-closed governance client for Pharma case operations."""

    def __init__(
        self,
        base_url: Optional[str] = None,
        api_key: Optional[str] = None,
        timeout: float = 10.0,
    ):
        self.base_url = (base_url or os.environ.get("OMNIGUARD_BASE_URL", "http://localhost:8000/v1")).rstrip("/")
        key = api_key or os.environ.get("OMNIGUARD_API_KEY")
        if key is None:
            raise ValueError("OMNIGUARD_API_KEY not configured")
        self.api_key = key
        self.timeout = timeout
        self._client: Optional[httpx.AsyncClient] = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                headers={"X-API-Key": self.api_key},
                timeout=self.timeout,
            )
        return self._client

    async def inspect_content(self, content: str) -> None:
        """Inspect content through OmniGuard. Raises GovernanceError on block/failure."""
        try:
            client = await self._get_client()
            resp = await client.post(
                "/chat/completions",
                json={"model": "omniguard-2.0", "messages": [{"role": "user", "content": content}]},
            )
        except Exception as exc:
            logger.warning("OmniGuard governance unreachable: %s", exc)
            raise GovernanceError("governance_unreachable") from exc

        if resp.status_code < 200 or resp.status_code >= 300:
            raise GovernanceError(f"governance_http_{resp.status_code}")

        decision = resp.headers.get("X-Governance-Decision", "BLOCK")
        if decision != "ALLOW":
            raise GovernanceError("governance_blocked")

    async def close(self) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None
