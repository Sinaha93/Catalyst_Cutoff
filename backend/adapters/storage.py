import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from backend.domain.errors import WorkflowError

SCHEMA_VERSION = 6
CHOICE_SCHEMA = '''CREATE TABLE choice_event (
    id INTEGER PRIMARY KEY AUTOINCREMENT, category TEXT NOT NULL, name TEXT NOT NULL,
    active INTEGER NOT NULL CHECK(active IN (0,1)), created_at TEXT NOT NULL)'''
MASTER_SCHEMA = [
    '''CREATE TABLE master_version (id TEXT PRIMARY KEY, role TEXT NOT NULL, version INTEGER NOT NULL,
       effective_from TEXT NOT NULL, effective_to TEXT, reason TEXT NOT NULL, payload_json TEXT NOT NULL,
       created_at TEXT NOT NULL, UNIQUE(role,version))''',
    '''CREATE TABLE draft_master (draft_id TEXT NOT NULL REFERENCES draft(id), role TEXT NOT NULL,
       version_id TEXT NOT NULL REFERENCES master_version(id), PRIMARY KEY(draft_id,role))''',
    '''CREATE TRIGGER immutable_master_update BEFORE UPDATE ON master_version BEGIN SELECT RAISE(ABORT, 'immutable master'); END''',
    '''CREATE TRIGGER immutable_master_delete BEFORE DELETE ON master_version BEGIN SELECT RAISE(ABORT, 'immutable master'); END''',
]
CLOSING_SCHEMA = [
    '''CREATE TABLE monthly_decision (id TEXT PRIMARY KEY, draft_id TEXT NOT NULL REFERENCES draft(id),
       part TEXT NOT NULL, kind TEXT NOT NULL, revision INTEGER NOT NULL, fingerprint TEXT NOT NULL,
       payload_json TEXT NOT NULL, created_at TEXT NOT NULL, UNIQUE(draft_id,revision))''',
    '''CREATE TABLE closing_snapshot (id TEXT PRIMARY KEY, month TEXT NOT NULL, version INTEGER NOT NULL,
       draft_id TEXT NOT NULL REFERENCES draft(id), revision INTEGER NOT NULL, request_key TEXT NOT NULL UNIQUE,
       fingerprint TEXT NOT NULL, payload_json TEXT NOT NULL, created_at TEXT NOT NULL, UNIQUE(month,version))''',
    '''CREATE TABLE draft_lock (draft_id TEXT PRIMARY KEY REFERENCES draft(id), snapshot_id TEXT NOT NULL REFERENCES closing_snapshot(id))''',
    '''CREATE TABLE carry_reference (draft_id TEXT PRIMARY KEY REFERENCES draft(id), snapshot_id TEXT NOT NULL REFERENCES closing_snapshot(id))''',
    '''CREATE TABLE export_run (id TEXT PRIMARY KEY, snapshot_id TEXT NOT NULL REFERENCES closing_snapshot(id),
       relative_path TEXT NOT NULL, sha256 TEXT NOT NULL, created_at TEXT NOT NULL)''',
    '''CREATE TRIGGER immutable_closing_update BEFORE UPDATE ON closing_snapshot BEGIN SELECT RAISE(ABORT, 'immutable snapshot'); END''',
    '''CREATE TRIGGER immutable_closing_delete BEFORE DELETE ON closing_snapshot BEGIN SELECT RAISE(ABORT, 'immutable snapshot'); END''',
]
HOLD_SCHEMA = '''CREATE TABLE hold_decision (
    id TEXT PRIMARY KEY, draft_id TEXT NOT NULL REFERENCES draft(id),
    part TEXT NOT NULL, revision INTEGER NOT NULL, fingerprint TEXT NOT NULL,
    payload_json TEXT NOT NULL, created_at TEXT NOT NULL,
    UNIQUE(draft_id, revision))'''
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
            if version not in (0, 1, 2, 3, 4, 5, SCHEMA_VERSION):
                raise RuntimeError('지원하지 않는 DB 버전입니다. 기존 자료를 변경하지 않았습니다.')
            if version == 0 and conn.execute("SELECT 1 FROM sqlite_master WHERE type='table'").fetchone():
                raise RuntimeError('알 수 없는 DB입니다. 기존 자료를 변경하지 않았습니다.')
            conn.execute('PRAGMA journal_mode=WAL')
            if version in (1, 2, 3, 4, 5):
                # Preserve a consistent pre-migration DB, including committed WAL data.
                backup = self.root / 'backups' / f'before-schema-{SCHEMA_VERSION}-{uuid4().hex}.sqlite'
                with sqlite3.connect(backup) as destination:
                    conn.backup(destination)
        with self.connect(write=True) as conn:
            if version == 0:
                for statement in SCHEMA:
                    conn.execute(statement)
            if version < 2:
                for statement in IMPORT_SCHEMA:
                    conn.execute(statement)
            if version < 3:
                conn.execute(HOLD_SCHEMA)
            if version < 4:
                for statement in CLOSING_SCHEMA:
                    conn.execute(statement)
            if version < 5:
                for statement in MASTER_SCHEMA:
                    conn.execute(statement)
            if version < 6:
                conn.execute(CHOICE_SCHEMA)
            conn.execute(f'PRAGMA user_version={SCHEMA_VERSION}')
        with self.connect() as conn:
            if conn.execute('PRAGMA quick_check').fetchone()[0] != 'ok':
                raise RuntimeError('자료 DB 무결성 검사에 실패했습니다.')

    @staticmethod
    def read(conn, month):
        row = conn.execute("SELECT * FROM draft WHERE month=? AND status='active'", (month,)).fetchone()
        if row is None:
            raise WorkflowError('NOT_FOUND', '해당 월 작업을 먼저 시작해 주세요.', 404)
        result = dict(row)
        has_lock = conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='draft_lock'").fetchone()
        result['finalized'] = bool(has_lock and conn.execute('SELECT snapshot_id FROM draft_lock WHERE draft_id=?', (result['id'],)).fetchone())
        return result

    def get(self, month):
        with self.connect() as conn:
            return self.read(conn, month)

    def list(self):
        with self.connect() as conn:
            return [self.read(conn, row['month']) for row in conn.execute("SELECT month FROM draft WHERE status='active' ORDER BY month DESC")]

    def delete_month(self, month, revision):
        """Explicit permanent removal; shared originals and program masters survive."""
        files = []
        drafts = 'SELECT id FROM draft WHERE month=?'
        batches = f'SELECT id FROM import_batch WHERE draft_id IN ({drafts})'
        snapshots = 'SELECT id FROM closing_snapshot WHERE month=?'
        with self.connect(write=True) as conn:
            before = self.read(conn, month)
            if before['revision'] != revision:
                raise WorkflowError('REVISION_CONFLICT', '월 작업이 변경됐습니다. 최신 내용을 확인한 뒤 삭제해 주세요.', 409)
            dependencies = conn.execute('''SELECT DISTINCT d.month FROM carry_reference c
                JOIN draft d ON d.id=c.draft_id JOIN closing_snapshot s ON s.id=c.snapshot_id
                WHERE s.month=? AND d.month<>?''', (month,month)).fetchall()
            if dependencies:
                months = ', '.join(r['month'] for r in dependencies)
                raise WorkflowError('MONTH_IN_USE', f'{months} 작업이 이 월의 확정본을 이월로 사용하고 있습니다. 연결된 월을 먼저 정리해야 삭제할 수 있습니다.', 409)
            shared = conn.execute(f'''SELECT DISTINCT d.month FROM draft_source ds JOIN draft d ON d.id=ds.draft_id
                WHERE d.month<>? AND ds.batch_id IN ({batches})''', (month,month)).fetchall()
            if shared:
                raise WorkflowError('MONTH_IN_USE', '다른 월이 이 월의 등록 자료를 사용하고 있어 삭제할 수 없습니다.', 409)
            candidates = [dict(r) for r in conn.execute(f'SELECT DISTINCT f.* FROM source_file f JOIN import_batch b ON b.file_id=f.id WHERE b.draft_id IN ({drafts})',(month,))]
            protected = set()
            def collect(value):
                if isinstance(value,dict):
                    if value.get('file_id'): protected.add(value['file_id'])
                    for v in value.values():collect(v)
                elif isinstance(value,list):
                    for v in value:collect(v)
            for r in conn.execute('SELECT payload_json FROM master_version UNION ALL SELECT payload_json FROM closing_snapshot WHERE month<>?',(month,)):
                collect(json.loads(r[0]))
            outputs = [dict(r) for r in conn.execute(f'SELECT * FROM export_run WHERE snapshot_id IN ({snapshots})',(month,))]
            # Validate exact file targets before any DB or filesystem removal.
            for r in candidates + outputs:
                p=(self.root/r['relative_path']).resolve()
                folder='originals' if r in candidates else 'exports'
                if not p.is_relative_to(self.root/folder):
                    raise WorkflowError('DELETE_PATH', '보관 파일 경로가 올바르지 않아 삭제하지 않았습니다.',409)
            for table in ('source_selection_event','draft_source','draft_master','monthly_decision','hold_decision','carry_reference','draft_lock','audit_event'):
                conn.execute(f'DELETE FROM {table} WHERE draft_id IN ({drafts})',(month,))
            for table in ('source_review','source_record'):
                conn.execute(f'DELETE FROM {table} WHERE batch_id IN ({batches})',(month,))
            conn.execute(f'DELETE FROM import_batch WHERE draft_id IN ({drafts})',(month,))
            conn.execute(f'DELETE FROM export_run WHERE snapshot_id IN ({snapshots})',(month,))
            trigger = conn.execute("SELECT sql FROM sqlite_master WHERE type='trigger' AND name='immutable_closing_delete'").fetchone()
            if trigger:
                conn.execute('DROP TRIGGER immutable_closing_delete')
            conn.execute('DELETE FROM closing_snapshot WHERE month=?',(month,))
            if trigger:conn.execute(trigger[0])
            conn.execute('DELETE FROM draft WHERE month=?',(month,))
            conn.execute('DELETE FROM closing_month WHERE month=?',(month,))
            for r in candidates:
                if r['id'] not in protected and not conn.execute('SELECT 1 FROM import_batch WHERE file_id=?',(r['id'],)).fetchone():
                    conn.execute('DELETE FROM source_file WHERE id=?',(r['id'],))
                    files.append((self.root/r['relative_path']).resolve())
            files.extend((self.root/r['relative_path']).resolve() for r in outputs)
        # Only files no longer referenced above are removed, never an entire folder.
        failed=[]
        for p in files:
            try:p.unlink(missing_ok=True)
            except OSError:failed.append(p.name)
        return {'month':month,'deleted':True,'file_count':len(files)-len(failed),
                'warning':f'월 작업은 삭제했습니다. 사용 중인 파일 {len(failed)}개는 지우지 못했습니다.' if failed else None}

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
            if conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='master_version'").fetchone():
                for row in conn.execute('''SELECT * FROM master_version WHERE effective_from<=?
                    AND (effective_to IS NULL OR effective_to>=?) ORDER BY effective_from DESC,version DESC''', (month, month)):
                    conn.execute('INSERT OR IGNORE INTO draft_master VALUES(?,?,?)', (draft['id'],row['role'],row['id']))
            self.audit(conn, draft, 'started')
            return draft

    def reset_month(self, month, revision, reason):
        if not reason.strip() or len(reason)>1000:
            raise WorkflowError('RESET_REASON', '초기화 사유를 입력해 주세요.')
        with self.connect(write=True) as conn:
            before = self.read(conn, month)
            if before['finalized']:
                raise WorkflowError('MONTH_FINALIZED', '확정 월은 먼저 새 확정 버전 작업을 시작한 뒤 초안을 초기화해 주세요.', 409)
            if before['revision'] != revision:
                raise WorkflowError('REVISION_CONFLICT', '작업이 변경됐습니다. 최신 내용을 확인해 주세요.', 409)
            stamp = now(); new_id = uuid4().hex
            conn.execute("UPDATE draft SET status='discarded',revision=revision+1,updated_at=? WHERE id=?", (stamp,before['id']))
            archived = {**before,'status':'discarded','revision':revision+1,'reset_reason':reason}
            self.audit(conn,archived,'draft_archived',before)
            # Keep revisions monotonic across drafts so a stale browser cannot write
            # to the replacement draft using a coincidentally matching revision.
            conn.execute("INSERT INTO draft VALUES(?,?,?,'active','',?,?)", (new_id,month,revision+2,stamp,stamp))
            for table,columns in (('draft_source','role,batch_id'),('draft_master','role,version_id'),('carry_reference','snapshot_id')):
                conn.execute(f'INSERT INTO {table} SELECT ?,{columns} FROM {table} WHERE draft_id=?', (new_id,before['id']))
            # Preserve reusable masters and monthly originals. A new draft must
            # explicitly adopt its plan again; spreadsheet decisions are also reset.
            conn.execute("DELETE FROM draft_source WHERE draft_id=? AND role IN ('allocation_inputs','plan_master')", (new_id,))
            draft = self.read(conn,month)
            self.audit(conn,{**draft,'reset_from':before['id'],'reset_reason':reason},'month_reset',before)
            return draft

    def archives(self, month):
        with self.connect() as conn:
            return [dict(r) for r in conn.execute("SELECT id,revision,note,created_at,updated_at FROM draft WHERE month=? AND status='discarded' ORDER BY updated_at DESC",(month,))]

    def save(self, month, revision, note):
        with self.connect(write=True) as conn:
            before = self.read(conn, month)
            if before['finalized']:
                raise WorkflowError('MONTH_FINALIZED', '확정본은 변경할 수 없습니다. 재작업을 시작해 주세요.', 409)
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
