"""Pharma Intelligence OS — Python case review package.

Tenant-scoped ICSR case store with optimistic locking, append-only audit
chain, and SHA-256 draft export. Backs the /v1/cases* HTTP API exposed by
``pharma_next.main:application``.
"""

from .store import CaseStore, Conflict

__all__ = ["CaseStore", "Conflict"]
__version__ = "1.0.0-pre.1"
