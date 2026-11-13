"""Tests for audit-trail encryption at rest (AES-256-GCM)."""

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

import pytest

from pharma_next.cfr11 import CFR11Compliance


def _compliance(tmp_path):
    db = str(tmp_path / "enc.db")
    return CFR11Compliance(
        db,
        enabled=True,
        signing_key=Ed25519PrivateKey.generate(),
        encryption_key=AESGCM(AESGCM.generate_key(256)),
    )


def test_plaintext_never_persists(tmp_path):
    c = _compliance(tmp_path)
    c.record_event(None, "t1", "alice", "create", "case-1", 1, {"summary": "sensitive data"})

    import sqlite3

    with sqlite3.connect(str(tmp_path / "enc.db")) as db:
        row = db.execute(
            "SELECT nonce, ciphertext FROM cfr11_audit_events WHERE seq=1"
        ).fetchone()

    persisted = row[1].encode() if isinstance(row[1], str) else row[1]
    assert b"sensitive data" not in persisted
    # Decryption round-trips to the original body.
    body = c._open(row[0], row[1])
    assert body == {"summary": "sensitive data"}


def test_wrong_key_fails_at_rest(tmp_path):
    c1 = _compliance(tmp_path)
    c1.record_event(None, "t1", "alice", "create", "case-1", 1, {"summary": "s"})

    import sqlite3

    with sqlite3.connect(str(tmp_path / "enc.db")) as db:
        row = db.execute("SELECT nonce, ciphertext FROM cfr11_audit_events WHERE seq=1").fetchone()

    # A different encryption key authenticates nothing: GCM tag verification fails.
    c2 = _compliance(tmp_path)
    with pytest.raises((InvalidTag, ValueError)):
        c2._open(row[0], row[1])
