"""Basic validation and health contract regression tests."""

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from pharma_next.api import create_application
from pharma_next.models import CaseBody


def test_case_body_rejects_empty_summary():
    with pytest.raises(ValidationError):
        CaseBody(summary="")


def test_case_body_normalizes_source_refs():
    body = CaseBody(summary="Valid case", source_refs=["  source-1  "])
    assert body.source_refs == ["source-1"]


def test_case_body_rejects_excess_references():
    with pytest.raises(ValidationError):
        CaseBody(summary="Valid case", source_refs=["ref"] * 51)


def test_health_endpoint(tmp_path):
    from pharma_next.store import CaseStore

    app = create_application(CaseStore(str(tmp_path / "test-cases.db")))
    with TestClient(app) as client:
        response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"
