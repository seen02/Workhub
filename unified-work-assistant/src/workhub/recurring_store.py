"""Additive recurrence schema, durable request receipts, and occurrence leases."""
import json
import time
import uuid
from . import store


def init():
    with store.db() as c:
        c.executescript('''
        CREATE TABLE IF NOT EXISTS recurring_rules(
          id TEXT PRIMARY KEY, collection_id TEXT NOT NULL, parent_id TEXT NOT NULL,
          creator_sub TEXT NOT NULL, executor_sub TEXT NOT NULL, outline_id TEXT NOT NULL, revision INTEGER NOT NULL,
          state TEXT NOT NULL, body TEXT NOT NULL, next_date TEXT NOT NULL,
          created_at TEXT NOT NULL, updated_at TEXT NOT NULL, reason TEXT NOT NULL DEFAULT '');
        CREATE INDEX IF NOT EXISTS recurring_due ON recurring_rules(state,next_date);
        CREATE TABLE IF NOT EXISTS recurring_versions(
          rule_id TEXT NOT NULL, revision INTEGER NOT NULL, body TEXT NOT NULL,
          actor TEXT NOT NULL, at TEXT NOT NULL, PRIMARY KEY(rule_id,revision));
        CREATE TABLE IF NOT EXISTS recurring_occurrences(
          id TEXT PRIMARY KEY, rule_id TEXT NOT NULL, scheduled_date TEXT NOT NULL,
          revision INTEGER NOT NULL, snapshot TEXT NOT NULL, document_id TEXT NOT NULL UNIQUE,
          status TEXT NOT NULL, reason TEXT NOT NULL DEFAULT '', attempts INTEGER NOT NULL DEFAULT 0,
          lease TEXT, lease_until REAL NOT NULL DEFAULT 0, retry_at REAL NOT NULL DEFAULT 0,
          payload TEXT, result TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
          UNIQUE(rule_id,scheduled_date));
        CREATE INDEX IF NOT EXISTS recurring_retry ON recurring_occurrences(status,retry_at);
        CREATE TABLE IF NOT EXISTS recurring_requests(
          id TEXT PRIMARY KEY, actor TEXT NOT NULL, fingerprint TEXT NOT NULL,
          result TEXT NOT NULL, at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS recurring_events(
          seq INTEGER PRIMARY KEY AUTOINCREMENT,rule_id TEXT NOT NULL,actor TEXT NOT NULL,
          action TEXT NOT NULL,revision INTEGER NOT NULL,at TEXT NOT NULL);
        ''')


def rule(rule_id):
    with store.db() as c:
        r = c.execute('SELECT * FROM recurring_rules WHERE id=?', (rule_id,)).fetchone()
    return dict(r) if r else None


def complete_if_finished(rule_id):
    """Finish a bounded schedule only after its last reserved write has settled."""
    with store.db() as c:
        c.execute("UPDATE recurring_rules SET state='completed',reason='',revision=revision+1,updated_at=? "
                  "WHERE id=? AND next_date='' AND state IN ('active','needs_attention') "
                  "AND NOT EXISTS (SELECT 1 FROM recurring_occurrences WHERE rule_id=? "
                  "AND status IN ('reserved','creating','retry_wait','reconciling','needs_attention'))",
                  (store.now(), rule_id, rule_id))


def occurrence(occurrence_id):
    with store.db() as c:
        r = c.execute('SELECT * FROM recurring_occurrences WHERE id=?', (occurrence_id,)).fetchone()
    return dict(r) if r else None


def reserve(rule, day, status='reserved', reason=''):
    with store.db() as c:
        identity = reserve_in(c, rule, day, status, reason)
    return occurrence(identity)


def reserve_in(c, rule, day, status='reserved', reason=''):
    """Reserve once in the caller's transaction, including Outline's v4 document ID."""
    identity = str(uuid.uuid5(uuid.NAMESPACE_URL, 'workhub-recurring:' + rule['id'] + ':' + day))
    c.execute('INSERT OR IGNORE INTO recurring_occurrences '
              '(id,rule_id,scheduled_date,revision,snapshot,document_id,status,reason,created_at,updated_at) '
              'VALUES(?,?,?,?,?,?,?,?,?,?)',
              (identity, rule['id'], day, rule['revision'], store.dump(rule), str(uuid.uuid4()),
               status, reason, store.now(), store.now()))
    return identity


def prepare_document_id(occurrence_id, lease):
    """Repair only the old, rejected v5 reservation while holding its execution lease."""
    with store.db() as c:
        c.execute('BEGIN IMMEDIATE')
        row = c.execute('SELECT * FROM recurring_occurrences WHERE id=?', (occurrence_id,)).fetchone()
        if not row or row['lease'] != lease or row['lease_until'] <= time.time():
            raise ValueError('다른 작업자가 해당 회차를 확인하고 있습니다.')
        legacy_id = str(uuid.uuid5(uuid.NAMESPACE_URL, 'workhub-recurring-document:' + occurrence_id))
        if row['document_id'] == legacy_id and row['status'] == 'creating' and not row['result']:
            # Outline rejects v5 IDs before inserting a document. Never replace a v4
            # ID: it may belong to a document whose success response was lost.
            document_id = str(uuid.uuid4())
            payload = json.loads(row['payload']) if row['payload'] else None
            if payload is not None:
                if payload.get('documentId') != legacy_id:
                    raise ValueError('저장된 회차의 문서 ID를 확인하세요.')
                payload['documentId'] = document_id
            c.execute('UPDATE recurring_occurrences SET document_id=?,payload=?,updated_at=? '
                      'WHERE id=? AND lease=?',
                      (document_id, store.dump(payload) if payload is not None else None,
                       store.now(), occurrence_id, lease))
    return occurrence(occurrence_id)


def claim(occurrence_id):
    token = str(uuid.uuid4())
    with store.db() as c:
        c.execute('BEGIN IMMEDIATE')
        row = c.execute('SELECT * FROM recurring_occurrences WHERE id=?', (occurrence_id,)).fetchone()
        if (not row or row['status'] not in ('reserved', 'creating', 'retry_wait', 'reconciling')
                or row['lease_until'] > time.time() or row['retry_at'] > time.time()):
            return None
        c.execute("UPDATE recurring_occurrences SET status='creating',lease=?,lease_until=?,"
                  'attempts=attempts+1,updated_at=? WHERE id=?',
                  (token, time.time() + 180, store.now(), occurrence_id))
    return token


def finish(occurrence_id, lease, status, *, reason='', result=None, retry_at=0):
    with store.db() as c:
        c.execute('UPDATE recurring_occurrences SET status=?,reason=?,result=COALESCE(?,result),'
                  'lease=NULL,lease_until=0,retry_at=?,updated_at=? WHERE id=? AND lease=?',
                  (status, reason, store.dump(result) if result else None, retry_at,
                   store.now(), occurrence_id, lease))


def freeze_payload(occurrence_id, lease, payload):
    with store.db() as c:
        c.execute('UPDATE recurring_occurrences SET payload=COALESCE(payload,?) WHERE id=? AND lease=?',
                  (store.dump(payload), occurrence_id, lease))
        row = c.execute('SELECT payload,lease FROM recurring_occurrences WHERE id=?', (occurrence_id,)).fetchone()
        if not row or row['lease'] != lease:
            raise ValueError('다른 작업자가 해당 회차를 확인하고 있습니다.')
        return json.loads(row['payload'])
