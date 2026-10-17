"""Pydantic models for the Pharma Intelligence OS case review API.

Request/response schemas for the /v1/cases* endpoints.
"""

from __future__ import annotations

from typing import Any, List, Optional
from uuid import UUID

from pydantic import BaseModel, Field, field_validator


class CaseBody(BaseModel):
    """Editable case body: summary + evidence references only."""

    summary: str = Field(..., min_length=1, max_length=10000)
    source_refs: List[str] = Field(default_factory=list)

    @field_validator("source_refs")
    @classmethod
    def _validate_refs(cls, v: List[str]) -> List[str]:
        if len(v) > 50:
            raise ValueError("maximum 50 evidence references")
        for ref in v:
            if not isinstance(ref, str) or not 1 <= len(ref.strip()) <= 500:
                raise ValueError("each reference must be 1-500 characters")
        return [r.strip() for r in v]


class CaseCreateRequest(BaseModel):
    """Request to create a new ICSR case."""

    body: CaseBody


class CaseRevisionRequest(BaseModel):
    """Request to revise an existing case (optimistic locking via expected_version)."""

    expected_version: int = Field(..., ge=1)
    body: CaseBody


class CaseReviewRequest(BaseModel):
    """Request to submit a case review (independent reviewer required)."""

    expected_version: int = Field(..., ge=1)


class CaseResponse(BaseModel):
    """Case representation returned by the API."""

    tenant: str
    id: UUID
    version: int
    state: str
    editor: str
    body: dict

    class Config:
        from_attributes = True


class CaseHistoryEntry(BaseModel):
    """Single revision entry from the audit-backed history."""

    version: int
    state: str
    actor: str


class AuditEvent(BaseModel):
    """Append-only audit event."""

    seq: int
    tenant: str
    actor: str
    action: str
    case_id: Optional[str] = None
    version: Optional[int] = None
    at: str
    previous: str
    digest: str


class DraftExport(BaseModel):
    """SHA-256-signed draft export artifact."""

    artifact: dict[str, Any]
    sha256: str


class HealthResponse(BaseModel):
    status: str = "ok"
    service: str = "pharma-intelligence-os"
    version: str = "1.0.0-pre.1"
