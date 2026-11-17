"""Tests for the immutable, signed, hash-chained CFR 11 audit trail."""

import base64
import sqlite3

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from pharma_next.cfr11 import CFR11Compliance, GENESIS


def _make_crypto(tmp_path):
    signing_key = Ed25519PrivateKey.generate()
    encryption_key = AESGCM.generate_key(256)
    return (
        signing_key,
        base64.b64encode(signing_key.private_bytes_raw()).decode("ascii"),
        base64.b64encode(encryption_key).decode("ascii"),
    )


def _compliance(tmp_path, dual_authorization=True):
    signing_key, sk_b64, enc_b64 = _make_crypto(tmp_path)
    db = str(tmp_path / "cfr11.db")
    return CFR11Compliance(
        db,
        enabled=True,
        signing_key=signing_key,
        encryption_key=AESGCM(base64.b64decode(enc_b64)),
        dual_authorization=dual_authorization,
    ), sk_b64, enc_b64


def test_chain_verifies_and_links(tmp_path):
    c, _, _ = _compliance(tmp_path)
    e1 = c.record_event(None, "t1", "alice", "create", "case-1", 1, {"summary": "s"})
    e2 = c.record_event(None, "t1", "alice", "revise", "case-1", 2, {"summary": "s2"})
    e3 = c.record_event(None, "t2", "bob", "create", "case-2", 1, {"summary": "s3"})

    report = c.verify_chain("t1")
    assert report["ok"] is True
    assert report["events_checked"] == 2
    assert report["genesis"] == GENESIS
    assert report["decryption_ok"] is True

    report_all = c.verify_chain()
    assert report_all["ok"] is True
    assert report_all["events_checked"] == 3

    # Tenant filter.
    assert len(c.list_events("t1")) == 2
    assert len(c.list_events("t2")) == 1

    # Genesis row anchors to GENESIS.
    with sqlite3.connect(str(tmp_path / "cfr11.db")) as db:
        row = db.execute("SELECT previous FROM cfr11_audit_events WHERE seq=1").fetchone()
        assert row[0] == GENESIS
        # Every event references the previous digest.
        rows = db.execute("SELECT seq, previous, digest FROM cfr11_audit_events ORDER BY seq").fetchall()
        prev = GENESIS
        for seq, previous, digest in rows:
            assert previous == prev
            prev = digest


def test_tampering_is_detected(tmp_path):
    c, _, _ = _compliance(tmp_path)
    c.record_event(None, "t1", "alice", "create", "case-1", 1, {"summary": "s"})
    c.record_event(None, "t1", "alice", "revise", "case-1", 2, {"summary": "s2"})

    with sqlite3.connect(str(tmp_path / "cfr11.db")) as db:
        # Ciphertext tamper breaks digest chain and GCM authentication.
        db.execute("UPDATE cfr11_audit_events SET ciphertext='AAAA' WHERE seq=1")
        db.commit()
    report = c.verify_chain("t1")
    assert report["ok"] is False
    assert any(t["seq"] == 1 for t in report["tampered"])
    assert report["decryption_ok"] is False

    # Digest recomputed without re-signing breaks signature verification.
    c2 = CFR11Compliance(
        str(tmp_path / "cfr11b.db"), enabled=True,
        signing_key=Ed25519PrivateKey.generate(),
        encryption_key=AESGCM(AESGCM.generate_key(256)),
    )
    c2.record_event(None, "t9", "alice", "create", "case-1", 1, {"summary": "s"})
    import hashlib

    with sqlite3.connect(str(tmp_path / "cfr11b.db")) as db:
        row = db.execute(
            "SELECT nonce, ciphertext, previous FROM cfr11_audit_events WHERE seq=1"
        ).fetchone()
        new_digest = hashlib.sha256(b"tampered-digest").hexdigest()
        db.execute("UPDATE cfr11_audit_events SET digest=? WHERE seq=1", (new_digest,))
        db.commit()
    report2 = c2.verify_chain("t9")
    assert report2["ok"] is False
    assert any(t["seq"] == 1 and "digest" in t["reasons"] and "signature" in t["reasons"] for t in report2["tampered"])


def test_empty_chain_verifies(tmp_path):
    c, _, _ = _compliance(tmp_path)
    report = c.verify_chain("t1")
    assert report["ok"] is True
    assert report["events_checked"] == 0
