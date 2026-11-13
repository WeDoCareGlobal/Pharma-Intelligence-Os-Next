"""HTTP API for the Pharma Intelligence OS case review service.

Endpoints:
  GET  /health
  POST /v1/cases             (editor)
  GET  /v1/cases?tenant=     (reader)
  GET  /v1/cases/{case_id}   (reader)
  POST /v1/cases/{case_id}/revisions   (editor)
  POST /v1/cases/{case_id}/review      (reviewer, independent)
  POST /v1/cases/{case_id}/approve     (approver, dual authorization)
  GET  /v1/cases/{case_id}/draft       (approver; approved state required)
  GET  /v1/cases/{case_id}/history     (reader)
  GET  /v1/cfr11/audit                 (reader) — immutable signed trail
  GET  /v1/cfr11/audit/verify          (reader) — chain verification
  POST /v1/cfr11/e-sign                (authenticated) — electronic signature
  GET  /v1/cfr11/e-sign/{sig_id}/verify (reader)
  POST /v1/cfr11/roles                 (admin) — RBAC assignment
  GET  /v1/cfr11/roles                 (reader)
  GET  /v1/cfr11/authorizations        (reader) — dual-authorization grants

Identity is transported in headers (X-User-Id; X-User-Roles is advisory —
authoritative roles are stored and enforced by CFR11Compliance). When
CFR11_ENABLE=1 the middleware rejects non-HTTPS requests and stamps HSTS
on every response (encryption in transit).
"""

from __future__ import annotations

import os
from typing import Any, Optional
from uuid import UUID

from fastapi import Depends, FastAPI, Header, HTTPException, Path, Query, Request, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from .cfr11 import CFR11Compliance, cfr11_enabled
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


# --------------------------------------------------------------------------- #
# Request/response models for CFR 11 endpoints
# --------------------------------------------------------------------------- #
class ESignCreateRequest(BaseModel):
    purpose: str = Field(..., min_length=1, max_length=200, example="case_review")
    payload: dict[str, Any] = Field(..., example={"decision": "approved", "note": "..."})
    case_id: Optional[str] = None
    version: Optional[int] = Field(None, ge=1)


class RoleAssignRequest(BaseModel):
    user_id: str = Field(..., example="alice")
    role: str = Field(..., example="approver")
    tenant: str = Field(..., example="tenant-a")


class ApproveRequest(BaseModel):
    expected_version: int = Field(..., ge=1)


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _env_bool(name: str, default: bool = False) -> bool:
    return os.environ.get(name, "1" if default else "0").lower() in {"1", "true", "yes", "on"}


def _require_role(request: Request, user: dict, role: str, tenant: str) -> None:
    """403 unless the authenticated user holds role on tenant (admin bypass)."""
    if not cfr11_enabled():
        return
    compliance: Optional[CFR11Compliance] = request.app.state.cfr11
    if compliance is None:
        raise HTTPException(status_code=500, detail="compliance layer not configured")
    if role == "admin":
        allowed = compliance.has_role(user["user_id"], "admin", tenant)
    else:
        allowed = compliance.has_role(user["user_id"], role, tenant) or compliance.has_role(
            user["user_id"], "admin", tenant
        )
    if not allowed:
        raise HTTPException(status_code=403, detail=f"role {role} required on tenant {tenant}")


# --------------------------------------------------------------------------- #
# Application factory
# --------------------------------------------------------------------------- #
def create_application(store: Optional[CaseStore] = None) -> FastAPI:
    """Build the FastAPI app with the given store (or a default SQLite store)."""
    if store is None:
        db_path = os.environ.get("PHARMA_DATABASE", "./data/cases.db")
        db_dir = os.path.dirname(os.path.abspath(db_path))
        if db_dir and not os.path.isdir(db_dir):
            os.makedirs(db_dir, exist_ok=True)
        store = CaseStore(db_path)

    compliance: Optional[CFR11Compliance] = store.cfr11
    app = FastAPI(
        title="Pharma Intelligence OS — Case Review API",
        description=(
            "Tenant-scoped ICSR case review with 21 CFR Part 11 compliance: "
            "signed immutable audit trail, electronic signatures, RBAC with "
            "dual authorization, encryption at rest and in transit."
        ),
        version="1.0.0-pre.1",
    )
    app.state.cfr11 = compliance

    # ------------------------------------------------------------------ #
    # Middleware: encryption in transit + security headers
    # ------------------------------------------------------------------ #
    @app.middleware("http")
    async def transit_security(request: Request, call_next):
        if _env_bool("CFR11_REQUIRE_TLS"):
            proto = request.headers.get("x-forwarded-proto", request.url.scheme)
            if proto != "https":
                return JSONResponse(
                    status_code=status.HTTP_403_FORBIDDEN,
                    content={"detail": "https required"},
                )
        response = await call_next(request)
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        return response

    # ------------------------------------------------------------------ #
    # Identity
    # ------------------------------------------------------------------ #
    async def current_user(
        request: Request, x_user_id: Optional[str] = Header(default=None, alias="X-User-Id")
    ) -> dict:
        if not cfr11_enabled():
            return {"user_id": "api-client"}
        if not x_user_id:
            raise HTTPException(status_code=401, detail="X-User-Id required")
        return {"user_id": x_user_id}

    def _actor(user: dict) -> str:
        return user["user_id"] if cfr11_enabled() else "api-client"

    # ------------------------------------------------------------------ #
    # Health
    # ------------------------------------------------------------------ #
    @app.get("/health", response_model=HealthResponse, tags=["health"])
    async def health() -> HealthResponse:
        return HealthResponse()

    # ------------------------------------------------------------------ #
    # Cases
    # ------------------------------------------------------------------ #
    @app.post(
        "/v1/cases",
        response_model=CaseResponse,
        status_code=status.HTTP_201_CREATED,
        tags=["cases"],
    )
    async def create_case(
        request: Request,
        req: CaseCreateRequest,
        tenant: str = Query(...),
        user: dict = Depends(current_user),
    ):
        _require_role(request, user, "editor", tenant)
        try:
            case = store.create(tenant, _actor(user), req.body.model_dump())
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        return _case_to_response(case)

    @app.get("/v1/cases", response_model=list[CaseResponse], tags=["cases"])
    async def list_cases(
        request: Request,
        tenant: str = Query(...),
        user: dict = Depends(current_user),
    ):
        _require_role(request, user, "reader", tenant)
        results = store.scan_tenant(tenant) if hasattr(store, "scan_tenant") else []
        return [_case_to_response(c) for c in results]

    @app.get("/v1/cases/{case_id}", response_model=CaseResponse, tags=["cases"])
    async def read_case(
        request: Request,
        tenant: str = Query(...),
        case_id: UUID = Path(...),
        user: dict = Depends(current_user),
    ):
        _require_role(request, user, "reader", tenant)
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
        request: Request,
        req: CaseRevisionRequest,
        tenant: str = Query(...),
        case_id: UUID = Path(...),
        user: dict = Depends(current_user),
    ):
        _require_role(request, user, "editor", tenant)
        try:
            case = store.revise(
                tenant, _actor(user), str(case_id), req.expected_version, req.body.model_dump()
            )
        except KeyError:
            raise HTTPException(status_code=404, detail="case not found")
        except Conflict:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="stale revision")
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        return _case_to_response(case)

    @app.post("/v1/cases/{case_id}/review", response_model=CaseResponse, tags=["cases"])
    async def review_case(
        request: Request,
        req: CaseReviewRequest,
        tenant: str = Query(...),
        case_id: UUID = Path(...),
        user: dict = Depends(current_user),
    ):
        _require_role(request, user, "reviewer", tenant)
        try:
            case = store.review(tenant, _actor(user), str(case_id), req.expected_version)
        except KeyError:
            raise HTTPException(status_code=404, detail="case not found")
        except Conflict:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT, detail="stale or already reviewed"
            )
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc))
        return _case_to_response(case)

    @app.post("/v1/cases/{case_id}/approve", response_model=CaseResponse, tags=["cases"])
    async def approve_case(
        request: Request,
        req: ApproveRequest,
        tenant: str = Query(...),
        case_id: UUID = Path(...),
        user: dict = Depends(current_user),
    ):
        _require_role(request, user, "approver", tenant)
        try:
            case = store.approve(tenant, _actor(user), str(case_id), req.expected_version)
        except KeyError:
            raise HTTPException(status_code=404, detail="case not found")
        except Conflict as exc:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc))
        return _case_to_response(case)

    @app.get("/v1/cases/{case_id}/draft", response_model=DraftExport, tags=["cases"])
    async def export_draft(
        request: Request,
        tenant: str = Query(...),
        case_id: UUID = Path(...),
        user: dict = Depends(current_user),
    ):
        _require_role(request, user, "approver", tenant)
        try:
            result = store.export(tenant, _actor(user), str(case_id))
        except KeyError:
            raise HTTPException(status_code=404, detail="case not found")
        except Conflict as exc:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
        return result

    @app.get(
        "/v1/cases/{case_id}/history",
        response_model=list[CaseHistoryEntry],
        tags=["cases"],
    )
    async def case_history(
        request: Request,
        tenant: str = Query(...),
        case_id: UUID = Path(...),
        user: dict = Depends(current_user),
    ):
        _require_role(request, user, "reader", tenant)
        try:
            store.get(tenant, str(case_id))  # ensure case exists
        except KeyError:
            raise HTTPException(status_code=404, detail="case not found")
        return [
            CaseHistoryEntry(version=r["version"], state=r["state"], actor=r["actor"])
            for r in store.history(tenant, str(case_id))
        ]

    # ------------------------------------------------------------------ #
    # CFR 11: immutable audit trail
    # ------------------------------------------------------------------ #
    @app.get("/v1/cfr11/audit", tags=["cfr11"])
    async def audit_trail(
        request: Request,
        tenant: str = Query(...),
        verify: int = Query(default=0),
        user: dict = Depends(current_user),
    ):
        _require_role(request, user, "reader", tenant)
        compliance: CFR11Compliance = request.app.state.cfr11
        if compliance is None or not compliance.enabled:
            raise HTTPException(status_code=404, detail="CFR 11 audit trail not enabled")
        events = compliance.list_events(tenant)
        report = None
        if verify:
            report = compliance.verify_chain(tenant)
        return {"tenant": tenant, "events": events, "verification": report}

    @app.get("/v1/cfr11/audit/verify", tags=["cfr11"])
    async def audit_verify(
        request: Request,
        tenant: Optional[str] = Query(default=None),
        user: dict = Depends(current_user),
    ):
        _require_role(request, user, "reader", tenant or "")
        compliance: CFR11Compliance = request.app.state.cfr11
        if compliance is None or not compliance.enabled:
            raise HTTPException(status_code=404, detail="CFR 11 audit trail not enabled")
        return compliance.verify_chain(tenant)

    # ------------------------------------------------------------------ #
    # CFR 11: electronic signatures (11.100 / 11.200)
    # ------------------------------------------------------------------ #
    @app.post("/v1/cfr11/e-sign", tags=["cfr11"])
    async def create_e_signature(
        request: Request,
        req: ESignCreateRequest,
        tenant: str = Query(...),
        user: dict = Depends(current_user),
    ):
        _require_role(request, user, "reader", tenant)
        compliance: CFR11Compliance = request.app.state.cfr11
        if compliance is None or not compliance.enabled:
            raise HTTPException(status_code=404, detail="CFR 11 not enabled")
        try:
            return compliance.create_e_signature(
                tenant, user["user_id"], req.purpose, req.payload, req.case_id, req.version
            )
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc))

    @app.get("/v1/cfr11/e-sign/{sig_id}/verify", tags=["cfr11"])
    async def verify_e_signature(
        request: Request,
        sig_id: str = Path(...),
        user: dict = Depends(current_user),
    ):
        compliance: CFR11Compliance = request.app.state.cfr11
        if compliance is None or not compliance.enabled:
            raise HTTPException(status_code=404, detail="CFR 11 not enabled")
        tenant = compliance.signature_tenant(sig_id)
        if tenant is None:
            return {"valid": False, "error": "signature not found"}
        _require_role(request, user, "reader", tenant)
        return compliance.verify_e_signature(sig_id)

    # ------------------------------------------------------------------ #
    # CFR 11: RBAC
    # ------------------------------------------------------------------ #
    @app.post("/v1/cfr11/roles", tags=["cfr11"])
    async def assign_role(
        request: Request,
        req: RoleAssignRequest,
        user: dict = Depends(current_user),
    ):
        _require_role(request, user, "admin", req.tenant)
        compliance: CFR11Compliance = request.app.state.cfr11
        compliance.assign_role(req.user_id, req.role, req.tenant)
        return {"user_id": req.user_id, "role": req.role, "tenant": req.tenant}

    @app.get("/v1/cfr11/roles", tags=["cfr11"])
    async def list_roles(
        request: Request,
        user_id: Optional[str] = Query(default=None),
        tenant: Optional[str] = Query(default=None),
        user: dict = Depends(current_user),
    ):
        _require_role(request, user, "reader", tenant or "")
        compliance: CFR11Compliance = request.app.state.cfr11
        if compliance is None or not compliance.enabled:
            raise HTTPException(status_code=404, detail="CFR 11 not enabled")
        if user_id and tenant:
            return {
                "user_id": user_id,
                "tenant": tenant,
                "roles": compliance.user_roles(user_id, tenant),
            }
        return {"note": "provide user_id and tenant"}

    @app.get("/v1/cfr11/authorizations", tags=["cfr11"])
    async def list_authorizations(
        request: Request,
        tenant: str = Query(...),
        case_id: str = Query(...),
        version: int = Query(..., ge=1),
        user: dict = Depends(current_user),
    ):
        _require_role(request, user, "reader", tenant)
        compliance: CFR11Compliance = request.app.state.cfr11
        return compliance.approvals(tenant, case_id, version)

    # ------------------------------------------------------------------ #
    # Helpers
    # ------------------------------------------------------------------ #
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
