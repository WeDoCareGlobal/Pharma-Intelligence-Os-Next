import hashlib
import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Generator, Optional

from .cfr11 import CFR11Compliance, cfr11_enabled


class Conflict(ValueError):
    pass


@contextmanager
def _connect(path: str) -> Generator[sqlite3.Connection, None, None]:
    db = sqlite3.connect(path, timeout=10)
    try:
        db.row_factory = sqlite3.Row
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


class CaseStore:
    def __init__(self, path, cfr11: Optional[CFR11Compliance] = None):
        self.path = str(path)
        self.cfr11 = cfr11
        if self.cfr11 is None and cfr11_enabled():
            # Fail closed: signing and encryption keys must be configured.
            self.cfr11 = CFR11Compliance(self.path)
        with _connect(self.path) as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS cases (
                    tenant TEXT NOT NULL, id TEXT NOT NULL, version INTEGER NOT NULL,
                    state TEXT NOT NULL, editor TEXT NOT NULL, body TEXT NOT NULL,
                    PRIMARY KEY(tenant,id));
                CREATE TABLE IF NOT EXISTS revisions (
                    tenant TEXT NOT NULL, id TEXT NOT NULL, version INTEGER NOT NULL,
                    state TEXT NOT NULL, actor TEXT NOT NULL, body TEXT NOT NULL,
                    PRIMARY KEY(tenant,id,version));
                CREATE TABLE IF NOT EXISTS audit (
                    seq INTEGER PRIMARY KEY, tenant TEXT NOT NULL, body TEXT NOT NULL,
                    previous TEXT NOT NULL, digest TEXT NOT NULL);
            ''')
            if self.cfr11 is not None and self.cfr11.enabled:
                self.cfr11._init_schema()

    def connect(self):
        return _connect(self.path)

    @staticmethod
    def validate(body):
        if not isinstance(body, dict) or set(body) - {'summary', 'source_refs'}:
            raise ValueError('summary and source_refs only')
        summary = body.get('summary')
        refs = body.get('source_refs', [])
        if not isinstance(summary, str) or not 1 <= len(summary.strip()) <= 10000:
            raise ValueError('summary required, maximum 10000 characters')
        if not isinstance(refs, list) or len(refs) > 50 or any(not isinstance(r, str) or not 1 <= len(r) <= 500 for r in refs):
            raise ValueError('invalid evidence references')
        return json.dumps({'summary': summary.strip(), 'source_refs': refs}, sort_keys=True, allow_nan=False)

    def _event(self, db, tenant, actor, case_id, action, version):
        if self.cfr11 is not None and self.cfr11.enabled:
            self.cfr11.record_event(
                db, tenant, actor, action, case_id, version,
                body={"case_id": case_id, "version": version},
            )
            return
        row = db.execute('SELECT seq,digest FROM audit ORDER BY seq DESC LIMIT 1').fetchone()
        seq, previous = (row['seq'] + 1, row['digest']) if row else (1, 'GENESIS')
        body = json.dumps({'seq': seq, 'tenant': tenant, 'actor': actor, 'case_id': case_id,
                           'action': action, 'version': version,
                           'at': datetime.now(timezone.utc).isoformat()}, sort_keys=True)
        digest = hashlib.sha256((previous + body).encode()).hexdigest()
        db.execute('INSERT INTO audit VALUES (?,?,?,?,?)', (seq, tenant, body, previous, digest))

    def _revision(self, db, tenant, case_id, version, state, actor, body):
        db.execute('INSERT INTO revisions VALUES (?,?,?,?,?,?)', (tenant, case_id, version, state, actor, body))

    def create(self, tenant, actor, body):
        if not tenant or not actor:
            raise ValueError('authenticated identity required')
        encoded = self.validate(body)
        case_id = str(uuid.uuid4())
        with _connect(self.path) as db:
            db.execute('BEGIN IMMEDIATE')
            db.execute('INSERT INTO cases VALUES (?,?,?,?,?,?)', (tenant, case_id, 1, 'draft', actor, encoded))
            self._revision(db, tenant, case_id, 1, 'draft', actor, encoded)
            self._event(db, tenant, actor, case_id, 'created', 1)
        return self.get(tenant, case_id)

    def get(self, tenant, case_id):
        with _connect(self.path) as db:
            row = db.execute('SELECT * FROM cases WHERE tenant=? AND id=?', (tenant, case_id)).fetchone()
        if row is None:
            raise KeyError('case not found')
        result = dict(row)
        result['body'] = json.loads(result['body'])
        return result

    def revise(self, tenant, actor, case_id, expected_version, body):
        encoded = self.validate(body)
        with _connect(self.path) as db:
            db.execute('BEGIN IMMEDIATE')
            current = db.execute('SELECT * FROM cases WHERE tenant=? AND id=?', (tenant, case_id)).fetchone()
            if current is None:
                raise KeyError('case not found')
            if current['version'] != expected_version:
                raise Conflict('stale revision')
            version = expected_version + 1
            db.execute('UPDATE cases SET version=?,state=?,editor=?,body=? WHERE tenant=? AND id=?',
                       (version, 'draft', actor, encoded, tenant, case_id))
            self._revision(db, tenant, case_id, version, 'draft', actor, encoded)
            self._event(db, tenant, actor, case_id, 'revised', version)
        return self.get(tenant, case_id)

    def review(self, tenant, actor, case_id, expected_version):
        with _connect(self.path) as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT * FROM cases WHERE tenant=? AND id=?', (tenant, case_id)).fetchone()
            if row is None:
                raise KeyError('case not found')
            if row['version'] != expected_version or row['state'] != 'draft':
                raise Conflict('stale or already reviewed')
            if row['editor'] == actor:
                raise PermissionError('independent reviewer required')
            version = expected_version + 1
            db.execute('UPDATE cases SET version=?,state=? WHERE tenant=? AND id=?', (version, 'reviewed', tenant, case_id))
            self._revision(db, tenant, case_id, version, 'reviewed', actor, row['body'])
            self._event(db, tenant, actor, case_id, 'reviewed', version)
        return self.get(tenant, case_id)

    def approve(self, tenant, actor, case_id, expected_version):
        """Dual-authorization release of a reviewed case.

        Records one approver's authorization for the case version. When the
        required number of distinct approvers has authorized (1 or 2 per
        CFR11_DUAL_AUTHORIZATION), the case transitions to 'approved'. Only
        approved cases may be exported.
        """
        with _connect(self.path) as db:
            db.execute('BEGIN IMMEDIATE')
            current = db.execute('SELECT * FROM cases WHERE tenant=? AND id=?', (tenant, case_id)).fetchone()
            if current is None:
                raise KeyError('case not found')
            if current['version'] != expected_version:
                raise Conflict('stale revision')
            if current['state'] != 'reviewed':
                raise Conflict('case must be reviewed before approval')
            if self.cfr11 is not None and self.cfr11.enabled:
                if not self.cfr11.has_role(actor, 'approver', tenant):
                    raise PermissionError('approver role required')
                # Independence: the approver must not have edited or reviewed this version.
                if actor == current['editor']:
                    raise PermissionError('independent authorization required')
                last = db.execute(
                    'SELECT actor FROM revisions WHERE tenant=? AND id=? AND version=? ORDER BY version DESC LIMIT 1',
                    (tenant, case_id, expected_version),
                ).fetchone()
                if last is not None and last['actor'] == actor:
                    raise PermissionError('independent authorization required')
                result = self.cfr11.authorize(db, tenant, actor, case_id, expected_version)
                approved = result['approved']
            else:
                approved = True
            if approved:
                version = expected_version + 1
                db.execute('UPDATE cases SET version=?,state=? WHERE tenant=? AND id=?',
                           (version, 'approved', tenant, case_id))
                self._revision(db, tenant, case_id, version, 'approved', actor, current['body'])
                self._event(db, tenant, actor, case_id, 'approved', version)
            else:
                self._event(db, tenant, actor, case_id, 'authorization_recorded', expected_version)
        return self.get(tenant, case_id)

    def history(self, tenant, case_id):
        self.get(tenant, case_id)
        with _connect(self.path) as db:
            return [dict(r) for r in db.execute('SELECT version,state,actor FROM revisions WHERE tenant=? AND id=? ORDER BY version', (tenant, case_id))]

    def export(self, tenant, actor, case_id):
        case = self.get(tenant, case_id)
        required_state = 'approved' if (self.cfr11 is not None and self.cfr11.enabled) else 'reviewed'
        if case['state'] != required_state:
            raise Conflict(f'{required_state} required before export')
        artifact = {'schema_version': 1, 'type': 'case-working-draft', 'regulatory_validated': False,
                    'transmitted': False, 'case': case, 'history': self.history(tenant, case_id)}
        encoded = json.dumps(artifact, sort_keys=True, allow_nan=False)
        with _connect(self.path) as db:
            db.execute('BEGIN IMMEDIATE')
            current = db.execute('SELECT version,state FROM cases WHERE tenant=? AND id=?', (tenant, case_id)).fetchone()
            if current['version'] != case['version'] or current['state'] != case['state']:
                raise Conflict('case changed during export')
            self._event(db, tenant, actor, case_id, 'draft_exported', case['version'])
        return {'artifact': artifact, 'sha256': hashlib.sha256(encoded.encode()).hexdigest()}

    def scan_tenant(self, tenant: str) -> list[dict]:
        """List all cases for a tenant (used by the cases list endpoint)."""
        with _connect(self.path) as db:
            rows = db.execute(
                'SELECT * FROM cases WHERE tenant=? ORDER BY version DESC', (tenant,)
            ).fetchall()
        return [dict(r) for r in rows]

