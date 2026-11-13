"""21 CFR Part 11 compliance layer for Pharma Intelligence OS.

Immutable, timestamped, hash-chained and Ed25519-digitally-signed audit
trail, electronic signatures for human approvals, RBAC with dual
authorization, and AES-256-GCM encryption of audit records at rest.

Security properties
-------------------
* Append-only hash chain: every event binds the previous digest (GENESIS
  rooted), so deletion or reordering is detectable.
* Every audit event and e-signature is signed with the service Ed25519
  signing key; verification fails if any field is altered.
* Audit bodies and e-signature payloads are encrypted at rest with
  AES-256-GCM (per-row nonce); GCM authentication detects ciphertext
  tampering.
* Electronic signatures are bound to user, purpose, case and case
  version and can be created only once per (user, purpose, case,
  version) (21 CFR 11.100, 11.200).
* Releases require dual authorization: two distinct approvers must
  authorize a reviewed case before it reaches the approved state
  (21 CFR 11.10(i) intent / two-person rule).

Configuration (environment variables)
-------------------------------------
CFR11_ENABLE            = "1" to fail-closed enable signing/encryption/RBAC.
CFR11_SIGNING_KEY       = base64-encoded 32-byte Ed25519 seed (required when enabled).
CFR11_SIGNING_KEY_FILE  = path to a file holding the base64 seed or an Ed25519 PEM key.
CFR11_ENCRYPTION_KEY    = base64-encoded 32-byte AES-256 key (required when enabled).
CFR11_ENCRYPTION_KEY_FILE = path to a base64-encoded 32-byte AES key file.
CFR11_REQUIRE_TLS       = "1" to reject non-HTTPS requests (FastAPI middleware).
CFR11_DUAL_AUTHORIZATION= "1" to require two distinct approvers per release.
CFR11_ROLE_SEED         = "alice:admin,tenantA;bob:approver,tenantA" seed roles at boot.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Optional

from cryptography.exceptions import InvalidSignature, InvalidTag
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

GENESIS = "GENESIS"
_DUAL_THRESHOLD = 2


def env_bool(name: str, default: bool = False) -> bool:
    return os.environ.get(name, "1" if default else "0").lower() in {"1", "true", "yes", "on"}


def cfr11_enabled() -> bool:
    return env_bool("CFR11_ENABLE")


def _b64e(b: bytes) -> str:
    return base64.b64encode(b).decode("ascii")


def _b64d(s: str) -> bytes:
    return base64.b64decode(s.encode("ascii"))


def _utcnow() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _load_signing_key() -> Ed25519PrivateKey:
    raw = os.environ.get("CFR11_SIGNING_KEY")
    path = os.environ.get("CFR11_SIGNING_KEY_FILE")
    data: Optional[bytes] = None
    if path:
        with open(path, "rb") as fh:
            data = fh.read()
    elif raw:
        data = raw.encode("ascii")
    if data is None:
        raise ValueError("CFR11_SIGNING_KEY (or CFR11_SIGNING_KEY_FILE) is required when CFR11_ENABLE=1")
    if data.startswith(b"-----BEGIN"):
        key = serialization.load_pem_private_key(data, password=None)
    else:
        key = Ed25519PrivateKey.from_private_bytes(_b64d(data.decode("ascii").strip()))
    if not isinstance(key, Ed25519PrivateKey):
        raise ValueError("signing key is not an Ed25519 key")
    return key


def _load_encryption_key() -> AESGCM:
    raw = os.environ.get("CFR11_ENCRYPTION_KEY")
    path = os.environ.get("CFR11_ENCRYPTION_KEY_FILE")
    data: Optional[bytes] = None
    if path:
        with open(path, "rb") as fh:
            data = fh.read()
    elif raw:
        data = raw.encode("ascii")
    if data is None:
        raise ValueError("CFR11_ENCRYPTION_KEY (or CFR11_ENCRYPTION_KEY_FILE) is required when CFR11_ENABLE=1")
    key = _b64d(data.decode("ascii").strip()) if not data.startswith(b"-----BEGIN") else data
    if len(key) != 32:
        raise ValueError("CFR11_ENCRYPTION_KEY must be 32 bytes (base64-encoded)")
    return AESGCM(key)


@contextmanager
def _connect(path: str):
    db = sqlite3.connect(path, timeout=10)
    db.row_factory = sqlite3.Row
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


class CFR11Compliance:
    """CFR 11 compliance services bound to one SQLite database file."""

    def __init__(
        self,
        db_path: str,
        enabled: Optional[bool] = None,
        signing_key: Optional[Ed25519PrivateKey] = None,
        encryption_key: Optional[AESGCM] = None,
        dual_authorization: Optional[bool] = None,
    ) -> None:
        self.db_path = str(db_path)
        self.enabled = cfr11_enabled() if enabled is None else enabled
        if self.enabled:
            # Fail closed: signing and encryption keys are mandatory.
            self.signing_key = signing_key or _load_signing_key()
            self.encryption_key = encryption_key or _load_encryption_key()
        else:
            self.signing_key = signing_key
            self.encryption_key = encryption_key
        self.dual_authorization = (
            env_bool("CFR11_DUAL_AUTHORIZATION") if dual_authorization is None else dual_authorization
        )
        db_dir = os.path.dirname(os.path.abspath(self.db_path))
        if db_dir:
            os.makedirs(db_dir, exist_ok=True)
        self._init_schema()
        self._seed_roles_from_env()

    # ------------------------------------------------------------------ #
    # Schema
    # ------------------------------------------------------------------ #
    def _init_schema(self) -> None:
        with _connect(self.db_path) as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS cfr11_audit_events (
                    seq INTEGER PRIMARY KEY,
                    tenant TEXT NOT NULL,
                    actor TEXT NOT NULL,
                    action TEXT NOT NULL,
                    case_id TEXT,
                    version INTEGER,
                    at TEXT NOT NULL,
                    nonce TEXT NOT NULL,
                    ciphertext TEXT NOT NULL,
                    previous TEXT NOT NULL,
                    digest TEXT NOT NULL,
                    signature TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS cfr11_e_signatures (
                    id TEXT PRIMARY KEY,
                    tenant TEXT NOT NULL,
                    user_id TEXT NOT NULL,
                    purpose TEXT NOT NULL,
                    case_id TEXT,
                    version INTEGER,
                    at TEXT NOT NULL,
                    payload_hash TEXT NOT NULL,
                    nonce TEXT NOT NULL,
                    ciphertext TEXT NOT NULL,
                    signature TEXT NOT NULL
                );
                CREATE UNIQUE INDEX IF NOT EXISTS cfr11_esig_once
                    ON cfr11_e_signatures(tenant, user_id, purpose, case_id, version);
                CREATE TABLE IF NOT EXISTS cfr11_authorizations (
                    seq INTEGER PRIMARY KEY,
                    tenant TEXT NOT NULL,
                    case_id TEXT NOT NULL,
                    version INTEGER NOT NULL,
                    approver TEXT NOT NULL,
                    at TEXT NOT NULL,
                    nonce TEXT NOT NULL,
                    ciphertext TEXT NOT NULL,
                    signature TEXT NOT NULL,
                    UNIQUE(case_id, version, approver)
                );
                CREATE TABLE IF NOT EXISTS cfr11_roles (
                    user_id TEXT NOT NULL,
                    role TEXT NOT NULL,
                    tenant TEXT NOT NULL,
                    PRIMARY KEY (user_id, role, tenant)
                );
                """
            )

    # ------------------------------------------------------------------ #
    # Crypto primitives
    # ------------------------------------------------------------------ #
    def _seal(self, payload: dict) -> tuple[str, str]:
        assert self.encryption_key is not None
        plaintext = json.dumps(payload, sort_keys=True, allow_nan=False).encode()
        nonce = os.urandom(12)
        ciphertext = self.encryption_key.encrypt(nonce, plaintext, None)
        return _b64e(nonce), _b64e(ciphertext)

    def _open(self, nonce_b64: str, ciphertext_b64: str) -> dict:
        assert self.encryption_key is not None
        plaintext = self.encryption_key.decrypt(
            _b64d(nonce_b64), _b64d(ciphertext_b64), None
        )
        return json.loads(plaintext.decode())

    def _sign(self, message: bytes) -> str:
        assert self.signing_key is not None
        return _b64e(self.signing_key.sign(message))

    def _verify(self, public_key: Ed25519PublicKey, message: bytes, signature_b64: str) -> bool:
        try:
            public_key.verify(_b64d(signature_b64), message)
            return True
        except InvalidSignature:
            return False

    @property
    def _verification_key(self) -> Ed25519PublicKey:
        assert self.signing_key is not None
        return self.signing_key.public_key()

    # ------------------------------------------------------------------ #
    # Immutable audit trail
    # ------------------------------------------------------------------ #
    def record_event(
        self,
        db: Optional[sqlite3.Connection],
        tenant: str,
        actor: str,
        action: str,
        case_id: Optional[str] = None,
        version: Optional[int] = None,
        body: Optional[dict] = None,
    ) -> dict:
        """Append one signed, encrypted, hash-chained audit event.

        ``db`` may be a connection already inside a transaction (the store
        passes its own connection so the event commits atomically with the
        case change); when None a private connection/transaction is used.
        """
        if self.enabled and (self.signing_key is None or self.encryption_key is None):
            raise ValueError("CFR 11 signing/encryption keys not configured")

        def _append(conn: sqlite3.Connection) -> dict:
            row = conn.execute(
                "SELECT seq, digest FROM cfr11_audit_events ORDER BY seq DESC LIMIT 1"
            ).fetchone()
            seq = (row["seq"] + 1) if row else 1
            previous = row["digest"] if row else GENESIS
            at = _utcnow()
            nonce_b64, ciphertext_b64 = self._seal(body or {})
            digest_input = (previous + nonce_b64 + ciphertext_b64).encode()
            digest = hashlib.sha256(digest_input).hexdigest()
            canonical = (
                f"{seq}|{tenant}|{actor}|{action}|{case_id or ''}|{version or ''}|{at}|{digest}"
            ).encode()
            signature = self._sign(canonical)
            conn.execute(
                "INSERT INTO cfr11_audit_events VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    seq,
                    tenant,
                    actor,
                    action,
                    case_id,
                    version,
                    at,
                    nonce_b64,
                    ciphertext_b64,
                    previous,
                    digest,
                    signature,
                ),
            )
            return {
                "seq": seq,
                "tenant": tenant,
                "actor": actor,
                "action": action,
                "case_id": case_id,
                "version": version,
                "at": at,
                "previous": previous,
                "digest": digest,
                "signature": signature,
                "body": body,
            }

        own = db is None
        if own:
            with _connect(self.db_path) as conn:
                conn.execute("BEGIN IMMEDIATE")
                return _append(conn)
        return _append(db)

    def verify_chain(self, tenant: Optional[str] = None) -> dict:
        """Recompute the whole chain and validate every signature.

        Returns {"ok": bool, "events_checked": int, "tampered": [seq,...],
        "genesis": str, "decryption_ok": bool}.
        """
        with _connect(self.db_path) as db:
            rows = (
                db.execute(
                    "SELECT * FROM cfr11_audit_events WHERE tenant=? ORDER BY seq",
                    (tenant,),
                ).fetchall()
                if tenant
                else db.execute(
                    "SELECT * FROM cfr11_audit_events ORDER BY seq"
                ).fetchall()
            )

        tampered: list[dict] = []
        previous = GENESIS
        decryption_ok = True
        for row in rows:
            recomputed = hashlib.sha256(
                (row["previous"] + row["nonce"] + row["ciphertext"]).encode()
            ).hexdigest()
            reasons: list[str] = []
            if row["previous"] != previous:
                reasons.append("chain_link")
            if recomputed != row["digest"]:
                reasons.append("digest")
            canonical = (
                f"{row['seq']}|{row['tenant']}|{row['actor']}|{row['action']}|"
                f"{row['case_id'] or ''}|{row['version'] or ''}|{row['at']}|{row['digest']}"
            ).encode()
            if not self._verify(self._verification_key, canonical, row["signature"]):
                reasons.append("signature")
            try:
                self._open(row["nonce"], row["ciphertext"])
            except (InvalidTag, ValueError):
                decryption_ok = False
                reasons.append("decryption")
            if reasons:
                tampered.append({"seq": row["seq"], "reasons": reasons})
            previous = row["digest"]

        if rows and rows[0]["previous"] != GENESIS:
            tampered.insert(
                0, {"seq": rows[0]["seq"], "reasons": ["genesis"]}
            ) if not any(t["seq"] == rows[0]["seq"] for t in tampered) else None

        return {
            "ok": len(tampered) == 0 and decryption_ok,
            "events_checked": len(rows),
            "tampered": tampered,
            "genesis": GENESIS,
            "decryption_ok": decryption_ok,
        }

    # ------------------------------------------------------------------ #
    # Electronic signatures (21 CFR 11.100 / 11.200)
    # ------------------------------------------------------------------ #
    def create_e_signature(
        self,
        tenant: str,
        user_id: str,
        purpose: str,
        payload: dict,
        case_id: Optional[str] = None,
        version: Optional[int] = None,
    ) -> dict:
        """Sign a payload on behalf of a user.

        Bound to (tenant, user_id, purpose, case_id, version): a second
        signature for the same binding raises ValueError.
        """
        if self.enabled and self.signing_key is None:
            raise ValueError("CFR 11 signing key not configured")
        sig_id = str(uuid.uuid4())
        at = _utcnow()
        payload_canonical = json.dumps(payload, sort_keys=True, allow_nan=False).encode()
        payload_hash = hashlib.sha256(payload_canonical).hexdigest()

        def _create(conn: sqlite3.Connection) -> dict:
            existing = conn.execute(
                "SELECT id FROM cfr11_e_signatures WHERE tenant=? AND user_id=? AND purpose=? "
                "AND case_id=? AND version=?",
                (tenant, user_id, purpose, case_id, version),
            ).fetchone()
            if existing:
                raise ValueError("electronic signature already exists for this user/purpose/case/version")
            nonce_b64, ciphertext_b64 = self._seal(
                {"purpose": purpose, "case_id": case_id, "version": version, "payload_hash": payload_hash, "payload": payload}
            )
            canonical = f"{sig_id}|{tenant}|{user_id}|{purpose}|{at}|{payload_hash}".encode()
            signature = self._sign(canonical)
            conn.execute(
                "INSERT INTO cfr11_e_signatures VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (
                    sig_id,
                    tenant,
                    user_id,
                    purpose,
                    case_id,
                    version,
                    at,
                    payload_hash,
                    nonce_b64,
                    ciphertext_b64,
                    signature,
                ),
            )
            return {
                "id": sig_id,
                "tenant": tenant,
                "user_id": user_id,
                "purpose": purpose,
                "case_id": case_id,
                "version": version,
                "at": at,
                "payload_hash": payload_hash,
                "signature": signature,
            }

        with _connect(self.db_path) as conn:
            conn.execute("BEGIN IMMEDIATE")
            return _create(conn)

    def verify_e_signature(self, sig_id: str) -> dict:
        """Verify an electronic signature and decrypt its payload.

        Returns {"valid": bool, ...} including the decrypted payload when valid.
        """
        with _connect(self.db_path) as db:
            row = db.execute(
                "SELECT * FROM cfr11_e_signatures WHERE id=?", (sig_id,)
            ).fetchone()
        if row is None:
            return {"valid": False, "error": "signature not found"}

        canonical = (
            f"{row['id']}|{row['tenant']}|{row['user_id']}|{row['purpose']}|{row['at']}|{row['payload_hash']}"
        ).encode()
        signature_ok = self._verify(self._verification_key, canonical, row["signature"])
        try:
            payload = self._open(row["nonce"], row["ciphertext"])
            payload_hash_ok = (
                hashlib.sha256(
                    json.dumps(payload["payload"], sort_keys=True, allow_nan=False).encode()
                ).hexdigest()
                == row["payload_hash"]
            )
        except (InvalidTag, ValueError, KeyError):
            payload = None
            payload_hash_ok = False

        valid = signature_ok and payload_hash_ok
        return {
            "valid": valid,
            "id": sig_id,
            "tenant": row["tenant"],
            "user_id": row["user_id"],
            "purpose": row["purpose"],
            "case_id": row["case_id"],
            "version": row["version"],
            "at": row["at"],
            "payload_hash": row["payload_hash"],
            "payload": payload if valid else None,
        }

    # ------------------------------------------------------------------ #
    # RBAC
    # ------------------------------------------------------------------ #
    def assign_role(self, user_id: str, role: str, tenant: str) -> None:
        with _connect(self.db_path) as db:
            db.execute(
                "INSERT OR IGNORE INTO cfr11_roles VALUES (?,?,?)", (user_id, role, tenant)
            )

    def revoke_role(self, user_id: str, role: str, tenant: str) -> None:
        with _connect(self.db_path) as db:
            db.execute(
                "DELETE FROM cfr11_roles WHERE user_id=? AND role=? AND tenant=?",
                (user_id, role, tenant),
            )

    def has_role(self, user_id: str, role: str, tenant: str) -> bool:
        with _connect(self.db_path) as db:
            row = db.execute(
                "SELECT 1 FROM cfr11_roles WHERE user_id=? AND role=? AND tenant=?",
                (user_id, role, tenant),
            ).fetchone()
        return row is not None

    def user_roles(self, user_id: str, tenant: str) -> list[str]:
        with _connect(self.db_path) as db:
            rows = db.execute(
                "SELECT role FROM cfr11_roles WHERE user_id=? AND tenant=?",
                (user_id, tenant),
            ).fetchall()
        return [r["role"] for r in rows]

    def _seed_roles_from_env(self) -> None:
        seed = os.environ.get("CFR11_ROLE_SEED", "").strip()
        if not seed:
            return
        for entry in seed.split(";"):
            entry = entry.strip()
            if not entry:
                continue
            parts = entry.split(":")
            if len(parts) != 3:
                continue
            user_id, role, tenant = parts
            self.assign_role(user_id, role, tenant)

    # ------------------------------------------------------------------ #
    # Dual authorization
    # ------------------------------------------------------------------ #
    def required_approvals(self) -> int:
        return _DUAL_THRESHOLD if self.dual_authorization else 1

    def authorize(
        self,
        db: sqlite3.Connection,
        tenant: str,
        approver: str,
        case_id: str,
        version: int,
    ) -> dict:
        """Record one approver's authorization for a case version.

        Returns {"approvals": int, "required": int, "approved": bool}.
        Fail-closed on role/key misconfiguration.
        """
        if self.enabled and self.signing_key is None:
            raise ValueError("CFR 11 signing key not configured")
        # One authorization per approver per case version (INSERT OR FAIL semantics).
        at = _utcnow()
        nonce_b64, ciphertext_b64 = self._seal(
            {"approver": approver, "case_id": case_id, "version": version, "at": at}
        )
        try:
            digest_input = ("authorization|" + case_id + "|" + str(version) + "|" + at + "|" + nonce_b64 + "|" + ciphertext_b64).encode()
            digest = hashlib.sha256(digest_input).hexdigest()
            canonical = f"auth|{tenant}|{approver}|{case_id}|{version}|{at}|{digest}".encode()
            signature = self._sign(canonical)
            db.execute(
                "INSERT INTO cfr11_authorizations "
                "(tenant, case_id, version, approver, at, nonce, ciphertext, signature) "
                "VALUES (?,?,?,?,?,?,?,?)",
                (tenant, case_id, version, approver, at, nonce_b64, ciphertext_b64, signature),
            )
        except sqlite3.IntegrityError as exc:
            raise ValueError("approver already authorized this case version") from exc

        # Chain this authorization into the immutable audit trail as well.
        self.record_event(
            db, tenant, approver, "authorization", case_id, version,
            body={"count_pending": None},
        )

        rows = db.execute(
            "SELECT DISTINCT approver FROM cfr11_authorizations WHERE tenant=? AND case_id=? AND version=?",
            (tenant, case_id, version),
        ).fetchall()
        approvals = len(rows)
        return {
            "approvals": approvals,
            "required": self.required_approvals(),
            "approved": approvals >= self.required_approvals(),
        }

    def signature_tenant(self, sig_id: str) -> Optional[str]:
        with _connect(self.db_path) as db:
            row = db.execute(
                "SELECT tenant FROM cfr11_e_signatures WHERE id=?", (sig_id,)
            ).fetchone()
        return row["tenant"] if row else None

    def approvals(self, tenant: str, case_id: str, version: int) -> list[dict]:
        with _connect(self.db_path) as db:
            rows = db.execute(
                "SELECT approver, at FROM cfr11_authorizations WHERE tenant=? AND case_id=? AND version=? ORDER BY at",
                (tenant, case_id, version),
            ).fetchall()
        return [dict(r) for r in rows]

    def list_events(self, tenant: str) -> list[dict]:
        """Return decrypted audit events for a tenant, newest first."""
        with _connect(self.db_path) as db:
            rows = db.execute(
                "SELECT * FROM cfr11_audit_events WHERE tenant=? ORDER BY seq DESC", (tenant,)
            ).fetchall()
        events = []
        for row in rows:
            try:
                body = self._open(row["nonce"], row["ciphertext"])
            except (InvalidTag, ValueError):
                body = {"_decryption_failed": True}
            events.append(
                {
                    "seq": row["seq"],
                    "tenant": row["tenant"],
                    "actor": row["actor"],
                    "action": row["action"],
                    "case_id": row["case_id"],
                    "version": row["version"],
                    "at": row["at"],
                    "previous": row["previous"],
                    "digest": row["digest"],
                    "signature": row["signature"],
                    "body": body,
                }
            )
        return events
