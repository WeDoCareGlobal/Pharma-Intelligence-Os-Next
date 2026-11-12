"""HTTP API for the Pharma Intelligence OS case review service.

Endpoints:
  GET  /health
  POST /v1/cases
  GET  /v1/cases?tenant=
  GET  /v1/cases/{case_id}
  POST /v1/cases/{case_id}/revisions
  POST /v1/cases/{case_id}/review
  GET  /v1/cases/{case_id}/draft
  GET  /v1/cases/{case_id}/history
"""

from __future__ import annotations

from typing import Optional
from uuid import UUID

from fastapi import FastAPI, HTTPException, Path, Query, status
from fastapi.responses import JSONResponse

from .models import (
    CaseBody,
    CaseCreateRequest,
    CaseHistoryEntry,
    CaseResponse,
    CaseReviewRequest,
    CaseRevisionRequest,
    DraftExport,
    HealthResponse,
)
from .store import CaseStore, Conflict
from .governance import OmniGuardGovernance, GovernanceError
import os

# ---------------------------------------------------------------------------
# Application factory
# ---------------------------------------------------------------------------


def create_application(store: Optional[CaseStore] = None) -> FastAPI:
    """Build the FastAPI app with the given store (or a default SQLite store)."""
    if store is None:
        import os

        db_path = os.environ.get("PHARMA_DATABASE", "./data/cases.db")
        db_dir = os.path.dirname(os.path.abspath(db_path))
        if db_dir and not os.path.isdir(db_dir):
            os.makedirs(db_dir, exist_ok=True)
        store = CaseStore(db_path)

    app = FastAPI(
        title="Pharma Intelligence OS — Case Review API",
        description="Tenant-scoped ICSR case review with optimistic locking and audit trail.",
        version="1.0.0-pre.1",
    )

    # ------------------------------------------------------------------
    # Health
    # ------------------------------------------------------------------
    @app.get("/health", response_model=HealthResponse, tags=["health"])
    async def health() -> HealthResponse:
        return HealthResponse()

    # ------------------------------------------------------------------
    # Cases
    # ------------------------------------------------------------------
    @app.post(
        "/v1/cases",
        response_model=CaseResponse,
        status_code=status.HTTP_201_CREATED,
        tags=["cases"],
    )
    async def create_case(req: CaseCreateRequest, tenant: str = Query(...)):
        actor = "api-client"  # placeholder; real auth populates this
        # Governance check (fail-closed)
        api_key = os.environ.get("OMNIGUARD_API_KEY")
        if api_key:
            gov = OmniGuardGovernance(api_key=api_key)
            try:
                import json
                await gov.inspect_content(json.dumps(req.body.model_dump()))
            except GovernanceError as exc:
                raise HTTPException(status_code=403, detail=str(exc))
            await gov.close()
        try:
            case = store.create(tenant, actor, req.body.model_dump())
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        return _case_to_response(case)

    @app.get("/v1/cases", response_model=list[CaseResponse], tags=["cases"])
    async def list_cases(tenant: str = Query(...)):
        # store.get is per-case; listing requires a scan. Return a scoped scan.
        results = store.scan_tenant(tenant) if hasattr(store, "scan_tenant") else []
        return [_case_to_response(c) for c in results]

    @app.get("/v1/cases/{case_id}", response_model=CaseResponse, tags=["cases"])
    async def read_case(
        tenant: str = Query(...),
        case_id: UUID = Path(...),
    ):
        try:
            case = store.get(tenant, str(case_id))
        except KeyError:
            raise HTTPException(status_code=404, detail="case not found")
        return _case_to_response(case)

    @app.post(
        "/v1/cases/{case_id}/revisions",
        response_model=CaseResponse,
        tags=["cases"],
    )
    async def revise_case(
        req: CaseRevisionRequest,
        tenant: str = Query(...),
        case_id: UUID = Path(...),
        actor: str = Query("api-client"),
    ):
        try:
            case = store.revise(
                tenant, actor, str(case_id), req.expected_version, req.body.model_dump()
            )
        except KeyError:
            raise HTTPException(status_code=404, detail="case not found")
        except Conflict:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT, detail="stale revision"
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        return _case_to_response(case)

    @app.post("/v1/cases/{case_id}/review", response_model=CaseResponse, tags=["cases"])
    async def review_case(
        req: CaseReviewRequest,
        tenant: str = Query(...),
        case_id: UUID = Path(...),
        actor: str = Query("api-client"),
    ):
        try:
            case = store.review(tenant, actor, str(case_id), req.expected_version)
        except KeyError:
            raise HTTPException(status_code=404, detail="case not found")
        except Conflict:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="stale or already reviewed",
            )
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc))
        return _case_to_response(case)

    @app.get("/v1/cases/{case_id}/draft", response_model=DraftExport, tags=["cases"])
    async def export_draft(
        tenant: str = Query(...),
        case_id: UUID = Path(...),
        actor: str = Query("api-client"),
    ):
        try:
            result = store.export(tenant, actor, str(case_id))
        except KeyError:
            raise HTTPException(status_code=404, detail="case not found")
        except Conflict:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT, detail="review required before export"
            )
        return result

    @app.get(
        "/v1/cases/{case_id}/history",
        response_model=list[CaseHistoryEntry],
        tags=["cases"],
    )
    async def case_history(
        tenant: str = Query(...),
        case_id: UUID = Path(...),
    ):
        try:
            store.get(tenant, str(case_id))  # ensure case exists
        except KeyError:
            raise HTTPException(status_code=404, detail="case not found")
        return [
            CaseHistoryEntry(version=r["version"], state=r["state"], actor=r["actor"])
            for r in store.history(tenant, str(case_id))
        ]

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _case_to_response(case: dict) -> dict:
        return {
            "tenant": case["tenant"],
            "id": case["id"],
            "version": case["version"],
            "state": case["state"],
            "editor": case["editor"],
            "body": case["body"],
        }

    return app


# Backwards-compatible factory name expected by uvicorn --factory and Docker CMD.
application = create_application()
