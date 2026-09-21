"""Transactional local decision ledger. State transitions and export are server-owned."""
from datetime import datetime, timezone, date
from contextlib import contextmanager
import json
import sqlite3
import uuid

from engine import Invalid, canonical, fingerprint, plan, day, text


class Conflict(Invalid):
    pass


class Store:
    def __init__(self, path):
        self.path = str(path)
        with self.connect() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS runs (
                  id TEXT PRIMARY KEY, snapshot TEXT NOT NULL, result TEXT NOT NULL,
                  status TEXT NOT NULL, created_at TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS events (
                  seq INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT NOT NULL,
                  action TEXT NOT NULL, actor TEXT NOT NULL, reason TEXT NOT NULL,
                  at TEXT NOT NULL, snapshot_hash TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS exports (
                  run_id TEXT PRIMARY KEY, snapshot_hash TEXT NOT NULL UNIQUE, payload TEXT NOT NULL);
            ''')

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    @staticmethod
    def now():
        return datetime.now(timezone.utc).isoformat()

    def create(self, snapshot):
        result = plan(snapshot)
        run_id = str(uuid.uuid4())
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            db.execute('INSERT INTO runs VALUES (?, ?, ?, ?, ?)', (run_id, canonical(snapshot), canonical(result), 'PENDING', self.now()))
            # A replacement snapshot invalidates pending AND previously approved plans.
            db.execute("INSERT OR REPLACE INTO meta VALUES ('active_hash', ?)", (result['snapshot_hash'],))
            db.execute("INSERT OR REPLACE INTO meta VALUES ('active_run', ?)", (run_id,))
            db.execute('INSERT INTO events(run_id,action,actor,reason,at,snapshot_hash) VALUES (?,?,?,?,?,?)', (run_id, 'PLANNED', 'planner', 'Validated snapshot', self.now(), result['snapshot_hash']))
        return self.get(run_id)

    def _read(self, db, run_id):
        row = db.execute('SELECT * FROM runs WHERE id=?', (run_id,)).fetchone()
        if row is None:
            raise Invalid('Unknown run')
        return row, json.loads(row['snapshot']), json.loads(row['result'])

    def _current(self, db, snapshot, result, today, run_id):
        active = db.execute("SELECT value FROM meta WHERE key='active_hash'").fetchone()
        active_run = db.execute("SELECT value FROM meta WHERE key='active_run'").fetchone()
        if active is None or active['value'] != fingerprint(snapshot) or active_run['value'] != run_id:
            raise Conflict('A newer snapshot exists. Replan before approval or export.')
        if day(snapshot['as_of']) != today:
            raise Conflict('Snapshot is not from today. Refresh inventory and replan.')
        if fingerprint(plan(snapshot)) != fingerprint(result):
            raise Conflict('Engine or plan changed. Replan before approval or export.')

    def decide(self, run_id, action, actor, reason, snapshot_hash, today=None):
        if action not in ['APPROVED', 'REJECTED']:
            raise Invalid('Action must be APPROVED or REJECTED')
        text(actor, 'reviewer')
        text(reason, 'review reason')
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row, snapshot, result = self._read(db, run_id)
            if snapshot_hash != result['snapshot_hash']:
                raise Conflict('Snapshot hash does not match the reviewed plan')
            if row['status'] != 'PENDING':
                raise Conflict('Decision already recorded; create a new run for changes')
            if action == 'APPROVED':
                self._current(db, snapshot, result, today or date.today(), run_id)
                if not any(l['status'] == 'RECOMMEND' for l in result['lines']):
                    raise Conflict('No purchasable recommendations to approve')
            db.execute('UPDATE runs SET status=? WHERE id=?', (action, run_id))
            db.execute('INSERT INTO events(run_id,action,actor,reason,at,snapshot_hash) VALUES (?,?,?,?,?,?)', (run_id, action, actor.strip(), reason.strip(), self.now(), result['snapshot_hash']))
        return self.get(run_id)

    def get(self, run_id):
        with self.connect() as db:
            row, _, result = self._read(db, run_id)
            events = [dict(r) for r in db.execute('SELECT * FROM events WHERE run_id=? ORDER BY seq', (run_id,))]
            active = db.execute("SELECT value FROM meta WHERE key='active_run'").fetchone()
            return {'id': run_id, 'status': row['status'], 'created_at': row['created_at'], 'is_current': bool(active and active['value'] == run_id), 'result': result, 'events': events}

    def list_runs(self):
        with self.connect() as db:
            return [dict(r) for r in db.execute('SELECT id,status,created_at FROM runs ORDER BY created_at DESC LIMIT 20')]

    def export(self, run_id, today=None):
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row, snapshot, result = self._read(db, run_id)
            if row['status'] != 'APPROVED':
                raise Conflict('Human approval is required before draft requisition export')
            self._current(db, snapshot, result, today or date.today(), run_id)
            existing = db.execute('SELECT payload FROM exports WHERE run_id=?', (run_id,)).fetchone()
            if existing:
                return json.loads(existing['payload'])
            if db.execute('SELECT run_id FROM exports WHERE snapshot_hash=?', (result['snapshot_hash'],)).fetchone():
                raise Conflict('This snapshot already has an exported requisition. Reconcile inbound orders before replanning.')
            payload = {'schema_version': '1.0', 'requisition_id': 'NEXUS-' + run_id, 'status': 'DRAFT_NOT_SENT', 'warehouse': snapshot['warehouse'], 'currency': 'IDR', 'snapshot_hash': result['snapshot_hash'], 'engine_version': result['engine_version'], 'total_idr': result['total_cost_idr'], 'lines': [{'sku': l['sku'], 'unit': l['unit'], **{k: l['selected'][k] for k in ['offer_id', 'supplier', 'quantity', 'unit_cost_idr', 'cost_idr', 'arrival']}} for l in result['lines'] if l['status'] == 'RECOMMEND'], 'unresolved_skus': [l['sku'] for l in result['lines'] if l['status'] == 'BLOCKED'], 'approval': dict(db.execute("SELECT actor,reason,at FROM events WHERE run_id=? AND action='APPROVED'", (run_id,)).fetchone())}
            db.execute('INSERT INTO exports VALUES (?,?,?)', (run_id, result['snapshot_hash'], canonical(payload)))
            db.execute('INSERT INTO events(run_id,action,actor,reason,at,snapshot_hash) VALUES (?,?,?,?,?,?)', (run_id, 'EXPORTED', payload['approval']['actor'], 'Draft requisition only; no external dispatch', self.now(), result['snapshot_hash']))
            return payload
