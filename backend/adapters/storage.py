import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from backend.domain.errors import WorkflowError

SCHEMA_VERSION = 2
SCHEMA = [
    '''CREATE TABLE closing_month (
       month TEXT PRIMARY KEY, created_at TEXT NOT NULL)''',
    '''CREATE TABLE draft (
       id TEXT PRIMARY KEY, month TEXT NOT NULL REFERENCES closing_month(month),
       revision INTEGER NOT NULL CHECK(revision >= 1),
       status TEXT NOT NULL CHECK(status IN ('active', 'discarded')),
       note TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL, updated_at TEXT NOT NULL)''',
    "CREATE UNIQUE INDEX one_active_draft ON draft(month) WHERE status='active'",
    '''CREATE TABLE audit_event (
       id INTEGER PRIMARY KEY, draft_id TEXT NOT NULL REFERENCES draft(id),
       revision INTEGER NOT NULL, kind TEXT NOT NULL, occurred_at TEXT NOT NULL,
       before_json TEXT, after_json TEXT NOT NULL,
       UNIQUE(draft_id, revision))''',
]

IMPORT_SCHEMA = [
    '''CREATE TABLE source_review (
       batch_id TEXT NOT NULL REFERENCES import_batch(id), revision INTEGER NOT NULL,
       review_json TEXT NOT NULL, created_at TEXT NOT NULL, PRIMARY KEY(batch_id,revision))''',
    '''CREATE TABLE source_file (
       id TEXT PRIMARY KEY, sha256 TEXT NOT NULL UNIQUE, relative_path TEXT NOT NULL,
       byte_size INTEGER NOT NULL, created_at TEXT NOT NULL)''',
    '''CREATE TABLE import_batch (
       id TEXT PRIMARY KEY, draft_id TEXT NOT NULL REFERENCES draft(id),
       file_id TEXT NOT NULL REFERENCES source_file(id), filename TEXT NOT NULL,
       role TEXT NOT NULL, source_period TEXT NOT NULL, parser_version TEXT NOT NULL,
       status TEXT NOT NULL, result_json TEXT NOT NULL, created_at TEXT NOT NULL,
       UNIQUE(draft_id,file_id,role,source_period,parser_version))''',
    '''CREATE TABLE source_record (
       batch_id TEXT NOT NULL REFERENCES import_batch(id), ordinal INTEGER NOT NULL,
       sheet TEXT NOT NULL, row_number INTEGER NOT NULL, part TEXT, quantity TEXT,
       evidence_json TEXT NOT NULL, PRIMARY KEY(batch_id,ordinal))''',
    '''CREATE TABLE draft_source (
       draft_id TEXT NOT NULL REFERENCES draft(id), role TEXT NOT NULL,
       batch_id TEXT NOT NULL REFERENCES import_batch(id), PRIMARY KEY(draft_id,role))''',
    '''CREATE TABLE source_selection_event (
       id INTEGER PRIMARY KEY, draft_id TEXT NOT NULL REFERENCES draft(id),
       role TEXT NOT NULL, previous_batch_id TEXT REFERENCES import_batch(id),
       batch_id TEXT NOT NULL REFERENCES import_batch(id), occurred_at TEXT NOT NULL)''',
]


def now():
    return datetime.now(timezone.utc).isoformat(timespec='milliseconds')


class Store:
    def __init__(self, root: Path):
        self.root = root.resolve()
        self.path = self.root / 'database' / 'closing.sqlite'

    @contextmanager
    def connect(self, write=False):
        conn = sqlite3.connect(self.path, timeout=5, isolation_level=None)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute('PRAGMA foreign_keys=ON')
            conn.execute('PRAGMA synchronous=FULL')
            if write:
                conn.execute('BEGIN IMMEDIATE')
            yield conn
            if write:
                conn.commit()
        except BaseException:
            if write:
                conn.rollback()
            raise
        finally:
            conn.close()

    def initialize(self):
        for folder in ('database', 'originals', 'exports', 'backups', 'staging'):
            (self.root / folder).mkdir(parents=True, exist_ok=True)
        with self.connect() as conn:
            version = conn.execute('PRAGMA user_version').fetchone()[0]
            if version not in (0, 1, SCHEMA_VERSION):
                raise RuntimeError('지원하지 않는 DB 버전입니다. 기존 자료를 변경하지 않았습니다.')
            if version == 0 and conn.execute("SELECT 1 FROM sqlite_master WHERE type='table'").fetchone():
                raise RuntimeError('알 수 없는 DB입니다. 기존 자료를 변경하지 않았습니다.')
            conn.execute('PRAGMA journal_mode=WAL')
            if version == 1:
                # Preserve a consistent pre-migration DB, including committed WAL data.
                backup = self.root / 'backups' / f'before-schema-2-{uuid4().hex}.sqlite'
                with sqlite3.connect(backup) as destination:
                    conn.backup(destination)
        with self.connect(write=True) as conn:
            if version == 0:
                for statement in SCHEMA:
                    conn.execute(statement)
            if version < 2:
                for statement in IMPORT_SCHEMA:
                    conn.execute(statement)
                conn.execute(f'PRAGMA user_version={SCHEMA_VERSION}')
        with self.connect() as conn:
            if conn.execute('PRAGMA quick_check').fetchone()[0] != 'ok':
                raise RuntimeError('자료 DB 무결성 검사에 실패했습니다.')

    @staticmethod
    def read(conn, month):
        row = conn.execute("SELECT * FROM draft WHERE month=? AND status='active'", (month,)).fetchone()
        if row is None:
            raise WorkflowError('NOT_FOUND', '해당 월 작업을 먼저 시작해 주세요.', 404)
        return dict(row)

    def get(self, month):
        with self.connect() as conn:
            return self.read(conn, month)

    def list(self):
        with self.connect() as conn:
            return [dict(row) for row in conn.execute("SELECT * FROM draft WHERE status='active' ORDER BY month DESC")]

    @staticmethod
    def audit(conn, draft, kind, before=None):
        conn.execute('INSERT INTO audit_event(draft_id,revision,kind,occurred_at,before_json,after_json) VALUES(?,?,?,?,?,?)',
                     (draft['id'], draft['revision'], kind, now(),
                      json.dumps(before, ensure_ascii=False) if before is not None else None,
                      json.dumps(draft, ensure_ascii=False)))

    def start(self, month):
        with self.connect(write=True) as conn:
            row = conn.execute("SELECT id FROM draft WHERE month=? AND status='active'", (month,)).fetchone()
            if row:
                return self.read(conn, month)
            stamp = now()
            conn.execute('INSERT OR IGNORE INTO closing_month VALUES(?,?)', (month, stamp))
            conn.execute('INSERT INTO draft VALUES(?,?,1,\'active\',\'\',?,?)', (uuid4().hex, month, stamp, stamp))
            draft = self.read(conn, month)
            self.audit(conn, draft, 'started')
            return draft

    def save(self, month, revision, note):
        with self.connect(write=True) as conn:
            before = self.read(conn, month)
            if before['revision'] != revision:
                raise WorkflowError('REVISION_CONFLICT', '다른 화면에서 저장한 내용이 있습니다. 입력을 복사해 두고 최신 저장본을 불러와 주세요.', 409)
            if before['note'] == note:
                return before
            conn.execute('UPDATE draft SET note=?, revision=revision+1, updated_at=? WHERE id=?', (note, now(), before['id']))
            draft = self.read(conn, month)
            self.audit(conn, draft, 'note_saved', before)
            return draft

    def history(self, month):
        with self.connect() as conn:
            draft = self.read(conn, month)
            return [dict(row) for row in conn.execute(
                'SELECT revision,kind,occurred_at FROM audit_event WHERE draft_id=? ORDER BY revision DESC LIMIT 50', (draft['id'],))]
