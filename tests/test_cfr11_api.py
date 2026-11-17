"""API-level tests for the CFR 11 compliance endpoints."""

from fastapi.testclient import TestClient

from pharma_next.api import create_application
from pharma_next.cfr11 import CFR11Compliance
from pharma_next.store import CaseStore
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
import base64


def _app(tmp_path, monkeypatch):
    monkeypatch.setenv("CFR11_ENABLE", "1")
    monkeypatch.setenv("CFR11_DUAL_AUTHORIZATION", "1")
    signing_key = Ed25519PrivateKey.generate()
    enc_key = AESGCM.generate_key(256)
    monkeypatch.setenv("CFR11_SIGNING_KEY", base64.b64encode(signing_key.private_bytes_raw()).decode("ascii"))
    monkeypatch.setenv("CFR11_ENCRYPTION_KEY", base64.b64encode(enc_key).decode("ascii"))
    db = str(tmp_path / "api.db")
    cfr11 = CFR11Compliance(
        db, enabled=True, signing_key=signing_key, encryption_key=AESGCM(enc_key)
    )
    for user, role in [("alice", "editor"), ("alice", "reader"), ("bob", "reviewer"), ("bob", "reader"),
                       ("carol", "approver"), ("carol", "reader"), ("dave", "approver"), ("dave", "reader"),
                       ("eve", "admin"), ("eve", "reader")]:
        cfr11.assign_role(user, role, "t")
    store = CaseStore(db, cfr11=cfr11)
    return TestClient(create_application(store)), cfr11


def _headers(user):
    return {"X-User-Id": user}


def test_requires_authentication(tmp_path, monkeypatch):
    client, _ = _app(tmp_path, monkeypatch)
    r = client.post("/v1/cases", params={"tenant": "t"},
                    json={"body": {"summary": "s", "source_refs": []}})
    assert r.status_code == 401


def test_create_and_review_flow(tmp_path, monkeypatch):
    client, cfr11 = _app(tmp_path, monkeypatch)
    r = client.post("/v1/cases", params={"tenant": "t"}, headers=_headers("alice"),
                    json={"body": {"summary": "summary", "source_refs": ["ref-1"]}})
    assert r.status_code == 201, r.text
    case = r.json()
    assert case["state"] == "draft"

    # Non-reviewer rejected.
    r = client.post("/v1/cases/{}/review".format(case["id"]), params={"tenant": "t"},
                    headers=_headers("alice"), json={"expected_version": case["version"]})
    assert r.status_code == 403

    # Independent reviewer approves review.
    r = client.post("/v1/cases/{}/review".format(case["id"]), params={"tenant": "t"},
                    headers=_headers("bob"), json={"expected_version": case["version"]})
    assert r.status_code == 200, r.text
    reviewed = r.json()
    assert reviewed["state"] == "reviewed"

    # First approver: not enough (dual authorization).
    r = client.post("/v1/cases/{}/approve".format(case["id"]), params={"tenant": "t"},
                    headers=_headers("carol"), json={"expected_version": r.json()["version"]})
    assert r.status_code == 200
    assert r.json()["state"] == "reviewed"

    # Double authorization by same user rejected.
    r = client.post("/v1/cases/{}/approve".format(case["id"]), params={"tenant": "t"},
                    headers=_headers("carol"), json={"expected_version": r.json()["version"]})
    assert r.status_code == 409

    # Second approver releases.
    r = client.post("/v1/cases/{}/approve".format(case["id"]), params={"tenant": "t"},
                    headers=_headers("dave"), json={"expected_version": reviewed["version"]})
    assert r.status_code == 200
    assert r.json()["state"] == "approved"

    # Export needs approver role and approved state.
    r = client.get("/v1/cases/{}/draft".format(case["id"]), params={"tenant": "t"},
                   headers=_headers("alice"))
    assert r.status_code == 403
    r = client.get("/v1/cases/{}/draft".format(case["id"]), params={"tenant": "t"},
                   headers=_headers("carol"))
    assert r.status_code == 200
    assert "sha256" in r.json()


def test_reader_cannot_write(tmp_path, monkeypatch):
    client, _ = _app(tmp_path, monkeypatch)
    # bob is only a reviewer: cannot create.
    r = client.post("/v1/cases", params={"tenant": "t"}, headers=_headers("bob"),
                    json={"body": {"summary": "s", "source_refs": []}})
    assert r.status_code == 403


def test_audit_trail_and_verify(tmp_path, monkeypatch):
    client, _ = _app(tmp_path, monkeypatch)
    client.post("/v1/cases", params={"tenant": "t"}, headers=_headers("alice"),
                json={"body": {"summary": "s", "source_refs": []}})
    r = client.get("/v1/cfr11/audit", params={"tenant": "t", "verify": 1}, headers=_headers("eve"))
    assert r.status_code == 200, r.text
    body = r.json()
    assert len(body["events"]) >= 1
    assert body["verification"]["ok"] is True
    assert body["verification"]["events_checked"] >= 1

    r = client.get("/v1/cfr11/audit/verify", params={"tenant": "t"}, headers=_headers("eve"))
    assert r.status_code == 200
    assert r.json()["ok"] is True


def test_e_signature_endpoints(tmp_path, monkeypatch):
    client, _ = _app(tmp_path, monkeypatch)
    r = client.post("/v1/cfr11/e-sign", params={"tenant": "t"}, headers=_headers("alice"),
                    json={"purpose": "case_approval",
                          "payload": {"decision": "approve"},
                          "case_id": "case-1", "version": 1})
    assert r.status_code == 200, r.text
    sig_id = r.json()["id"]

    r = client.get("/v1/cfr11/e-sign/{}/verify".format(sig_id), headers=_headers("eve"))
    assert r.status_code == 200
    assert r.json()["valid"] is True

    # Reuse of same binding is rejected.
    r = client.post("/v1/cfr11/e-sign", params={"tenant": "t"}, headers=_headers("alice"),
                    json={"purpose": "case_approval",
                          "payload": {"decision": "approve"},
                          "case_id": "case-1", "version": 1})
    assert r.status_code == 409


def test_rbac_role_endpoint(tmp_path, monkeypatch):
    client, _ = _app(tmp_path, monkeypatch)
    r = client.post("/v1/cfr11/roles", headers=_headers("alice"),
                    json={"user_id": "fay", "role": "reader", "tenant": "t"})
    assert r.status_code == 403  # alice is not admin
    r = client.post("/v1/cfr11/roles", headers=_headers("eve"),
                    json={"user_id": "fay", "role": "reader", "tenant": "t"})
    assert r.status_code == 200
    r = client.get("/v1/cfr11/roles", params={"user_id": "fay", "tenant": "t"},
                   headers=_headers("eve"))
    assert r.status_code == 200
    assert "reader" in r.json()["roles"]


def test_tls_middleware_rejects_plaintext(tmp_path, monkeypatch):
    monkeypatch.setenv("CFR11_REQUIRE_TLS", "1")
    client, _ = _app(tmp_path, monkeypatch)
    r = client.get("/health")
    assert r.status_code == 403
    r = client.get("/health", headers={"x-forwarded-proto": "https"})
    assert r.status_code == 200
    assert r.headers["strict-transport-security"].startswith("max-age=31536000")
