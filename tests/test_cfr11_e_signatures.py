"""Tests for electronic signatures (21 CFR 11.100 / 11.200)."""

import base64
import sqlite3

import pytest
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from pharma_next.cfr11 import CFR11Compliance


def _compliance(tmp_path):
    signing_key = Ed25519PrivateKey.generate()
    enc_key = AESGCM.generate_key(256)
    db = str(tmp_path / "esig.db")
    return CFR11Compliance(
        db,
        enabled=True,
        signing_key=signing_key,
        encryption_key=AESGCM(enc_key),
    )


def test_sign_and_verify(tmp_path):
    c = _compliance(tmp_path)
    sig = c.create_e_signature(
        "t1", "alice", "case_review",
        {"decision": "approved", "case_id": "case-1", "version": 1},
        case_id="case-1", version=1,
    )
    assert sig["user_id"] == "alice"
    assert sig["purpose"] == "case_review"
    assert sig["payload_hash"] and len(sig["signature"]) > 0

    result = c.verify_e_signature(sig["id"])
    assert result["valid"] is True
    assert result["user_id"] == "alice"
    assert result["purpose"] == "case_review"
    assert result["case_id"] == "case-1"
    assert result["payload"]["payload"]["decision"] == "approved"


def test_signature_bound_to_user_purpose_case_version(tmp_path):
    c = _compliance(tmp_path)
    payload = {"decision": "approved"}
    c.create_e_signature("t1", "alice", "case_review", payload, "case-1", 1)
    with pytest.raises(ValueError, match="already exists"):
        c.create_e_signature("t1", "alice", "case_review", payload, "case-1", 1)
    # Same user/purpose but different case or version may be re-signed.
    c.create_e_signature("t1", "alice", "case_review", payload, "case-1", 2)
    c.create_e_signature("t1", "alice", "case_review", payload, "case-2", 1)
    # Different user may sign the same binding.
    c.create_e_signature("t1", "bob", "case_review", payload, "case-1", 1)


def test_tampered_signature_fails(tmp_path):
    c = _compliance(tmp_path)
    sig = c.create_e_signature(
        "t1", "alice", "case_approval",
        {"decision": "reject"}, case_id="case-1", version=1,
    )

    with sqlite3.connect(str(tmp_path / "esig.db")) as db:
        db.execute("UPDATE cfr11_e_signatures SET payload_hash='deadbeef' WHERE id=?", (sig["id"],))
        db.commit()
    assert c.verify_e_signature(sig["id"])["valid"] is False


def test_foreign_key_cannot_verify(tmp_path):
    ca = _compliance(tmp_path)
    sig = ca.create_e_signature(
        "t1", "alice", "case_approval",
        {"decision": "approve"}, case_id="case-1", version=1,
    )
    # A compliance instance with a different signing key must reject it.
    cb = _compliance(tmp_path)
    assert cb.verify_e_signature(sig["id"])["valid"] is False
    # The original key still verifies it.
    assert ca.verify_e_signature(sig["id"])["valid"] is True
