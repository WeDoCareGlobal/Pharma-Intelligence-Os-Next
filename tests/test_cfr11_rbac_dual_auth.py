"""Tests for RBAC and dual authorization (two-person rule)."""

import base64

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from pharma_next.cfr11 import CFR11Compliance
from pharma_next.store import CaseStore, Conflict


def _store_with_cfr11(tmp_path, dual_authorization=True):
    signing_key = Ed25519PrivateKey.generate()
    enc_key = AESGCM.generate_key(256)
    db = str(tmp_path / "pharma.db")
    cfr11 = CFR11Compliance(
        db,
        enabled=True,
        signing_key=signing_key,
        encryption_key=AESGCM(enc_key),
        dual_authorization=dual_authorization,
    )
    for user, role in [("alice", "editor"), ("bob", "reviewer"), ("carol", "approver"),
                       ("dave", "approver"), ("eve", "admin")]:
        cfr11.assign_role(user, role, "t")
    return CaseStore(db, cfr11=cfr11), cfr11


def test_roles(tmp_path):
    store, cfr11 = _store_with_cfr11(tmp_path)
    assert cfr11.has_role("alice", "editor", "t") is True
    assert cfr11.has_role("alice", "approver", "t") is False
    assert cfr11.user_roles("eve", "t") == ["admin"]
    cfr11.revoke_role("eve", "admin", "t")
    assert cfr11.has_role("eve", "admin", "t") is False


def test_independent_reviewer(tmp_path):
    store, _ = _store_with_cfr11(tmp_path)
    case = store.create("t", "alice", {"summary": "s", "source_refs": []})
    with pytest.raises(PermissionError, match="independent reviewer"):
        store.review("t", "alice", case["id"], case["version"])
    store.review("t", "bob", case["id"], case["version"])
    assert store.get("t", case["id"])["state"] == "reviewed"


def test_dual_authorization_release(tmp_path):
    store, cfr11 = _store_with_cfr11(tmp_path)
    case = store.create("t", "alice", {"summary": "s", "source_refs": []})
    store.review("t", "bob", case["id"], case["version"])
    reviewed = store.get("t", case["id"])
    assert reviewed["state"] == "reviewed"

    # First approver alone is not enough with dual authorization.
    r1 = store.approve("t", "carol", case["id"], reviewed["version"])
    assert r1["state"] == "reviewed"
    assert len(cfr11.approvals("t", case["id"], reviewed["version"])) == 1

    # Same approver may not authorize twice.
    with pytest.raises(ValueError, match="already authorized"):
        store.approve("t", "carol", case["id"], reviewed["version"])

    # Non-approver is rejected.
    with pytest.raises(PermissionError, match="approver role required"):
        store.approve("t", "alice", case["id"], reviewed["version"])

    # Grant alice the approver role: she is the editor, so independence blocks her.
    cfr11.assign_role("alice", "approver", "t")
    with pytest.raises(PermissionError, match="independent authorization"):
        store.approve("t", "alice", case["id"], reviewed["version"])

    # Second approver releases the case.
    r2 = store.approve("t", "dave", case["id"], reviewed["version"])
    assert r2["state"] == "approved"
    assert r2["version"] == reviewed["version"] + 1
    assert len(cfr11.approvals("t", case["id"], reviewed["version"])) == 2


def test_export_requires_approval(tmp_path):
    store, _ = _store_with_cfr11(tmp_path)
    case = store.create("t", "alice", {"summary": "s", "source_refs": []})
    store.review("t", "bob", case["id"], case["version"])
    reviewed = store.get("t", case["id"])
    with pytest.raises(Conflict, match="approved"):
        store.export("t", "carol", case["id"])
    store.approve("t", "carol", case["id"], reviewed["version"])
    store.approve("t", "dave", case["id"], reviewed["version"])
    result = store.export("t", "carol", case["id"])
    assert result["artifact"]["case"]["state"] == "approved"
    assert "sha256" in result


def test_single_authorization_when_dual_disabled(tmp_path):
    store, _ = _store_with_cfr11(tmp_path, dual_authorization=False)
    case = store.create("t", "alice", {"summary": "s", "source_refs": []})
    store.review("t", "bob", case["id"], case["version"])
    reviewed = store.get("t", case["id"])
    released = store.approve("t", "carol", case["id"], reviewed["version"])
    assert released["state"] == "approved"
