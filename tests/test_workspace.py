import os
import sqlite3
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient

from backend.adapters.lock import AlreadyRunning, WorkspaceLock
from backend.adapters.storage import Store
from backend.api.app import create_app
from backend.application.workflow import Workflow
from backend.domain.errors import WorkflowError


@pytest.fixture
def store(tmp_path):
    result = Store(tmp_path / '한글 자료 폴더')
    result.initialize()
    return result


def test_restore_and_same_month_is_idempotent(store):
    first = store.start('2026-09')
    saved = store.save('2026-09', first['revision'], '원본 PDF 확인 예정')
    reopened = Store(store.root)
    reopened.initialize()
    assert reopened.get('2026-09') == saved
    assert reopened.start('2026-09') == saved
    assert len(reopened.list()) == 1
    assert [h['revision'] for h in reopened.history('2026-09')] == [2, 1]


def test_concurrent_start_and_stale_save(store):
    with ThreadPoolExecutor(max_workers=4) as pool:
        rows = list(pool.map(store.start, ['2026-09'] * 8))
    assert len({row['id'] for row in rows}) == 1
    store.save('2026-09', 1, '다른 창 저장')
    with pytest.raises(WorkflowError) as error:
        store.save('2026-09', 1, '오래된 화면')
    assert error.value.code == 'REVISION_CONFLICT'
    assert store.get('2026-09')['note'] == '다른 창 저장'


def test_audit_failure_rolls_back_draft(store):
    original = store.start('2026-09')
    with store.connect(write=True) as conn:
        conn.execute("CREATE TRIGGER fail_audit BEFORE INSERT ON audit_event BEGIN SELECT RAISE(ABORT, 'injected failure'); END")
    with pytest.raises(sqlite3.IntegrityError):
        store.save('2026-09', 1, '저장되면 안 되는 메모')
    assert store.get('2026-09') == original
    assert len(store.history('2026-09')) == 1


def test_future_schema_is_not_overwritten(store):
    with store.connect() as conn:
        conn.execute('PRAGMA user_version=99')
    with pytest.raises(RuntimeError):
        store.initialize()
    with store.connect() as conn:
        assert conn.execute('PRAGMA user_version').fetchone()[0] == 99


@pytest.mark.parametrize('month', ['2026-00', '2026-13', '2026-1', '../2026', '9999-09'])
def test_invalid_month(store, month):
    with pytest.raises(WorkflowError):
        Workflow(store).start(month)
    assert store.list() == []


def test_lock_released_after_process_crash(tmp_path):
    script = 'import sys,time; from pathlib import Path; from backend.adapters.lock import WorkspaceLock; lock=WorkspaceLock(Path(sys.argv[1])); lock.__enter__(); print("LOCKED",flush=True); time.sleep(60)'
    process = subprocess.Popen([sys.executable, '-c', script, str(tmp_path)], stdout=subprocess.PIPE, text=True)
    try:
        assert process.stdout.readline().strip() == 'LOCKED'
        with pytest.raises(AlreadyRunning):
            with WorkspaceLock(tmp_path):
                pass
    finally:
        # Windows venv launchers may delegate to a child interpreter. Kill the
        # entire test process tree, not only its wrapper, to simulate a crash.
        if os.name == 'nt' and process.poll() is None:
            subprocess.run(['taskkill', '/PID', str(process.pid), '/T', '/F'], check=True, capture_output=True)
        else:
            process.kill()
        process.wait(timeout=10)
        process.stdout.close()
    with WorkspaceLock(tmp_path):
        pass


def test_api_session_validation_conflict_and_restart(tmp_path):
    with TestClient(create_app(tmp_path), base_url='http://127.0.0.1') as client:
        token = client.get('/api/session').json()['token']
        headers = {'Origin': 'http://127.0.0.1', 'X-Session-Token': token}
        assert client.post('/api/months', json={'month': '2026-09'}).status_code == 403
        assert client.post('/api/months', headers={**headers, 'Origin':'https://unrelated.example'}, json={'month':'2026-09'}).status_code == 403
        assert client.get('/api/session', headers={'Host':'unrelated.example'}).status_code == 403
        result = client.post('/api/months', headers=headers, json={'month':'2026-09'})
        assert result.status_code == 200
        assert result.json()['revision'] == 1
        assert client.patch('/api/months/2026-09', headers=headers, json={'expected_revision':1,'note':'확인할 자료'}).status_code == 200
        assert client.patch('/api/months/2026-09', headers=headers, json={'expected_revision':1,'note':'충돌'}).status_code == 409
        assert client.patch('/api/months/2026-09', headers=headers, json={'expected_revision':True,'note':'오류'}).status_code == 422
        assert client.post('/api/months', headers=headers, json={'month':'2026-09','unexpected':1}).status_code == 422
        with pytest.raises(AlreadyRunning):
            with TestClient(create_app(tmp_path), base_url='http://127.0.0.1'):
                pass
    with TestClient(create_app(tmp_path), base_url='http://127.0.0.1') as client:
        assert client.get('/api/months/2026-09').json()['note'] == '확인할 자료'
        assert client.post('/api/months', headers=headers, json={'month':'2026-10'}).status_code == 403


def test_api_storage_failure_has_actionable_error(tmp_path, monkeypatch):
    app = create_app(tmp_path)
    with TestClient(app, base_url='http://127.0.0.1') as client:
        token = client.get('/api/session').json()['token']
        headers = {'Origin':'http://127.0.0.1', 'X-Session-Token':token}
        client.post('/api/months', headers=headers, json={'month':'2026-09'})
        def fail(*_):
            raise sqlite3.OperationalError('disk failure')
        monkeypatch.setattr(app.state.store, 'save', fail)
        result = client.patch('/api/months/2026-09', headers=headers, json={'expected_revision':1,'note':'보존할 입력'})
        assert result.status_code == 503
        assert result.json()['code'] == 'STORAGE_FAILED'
        assert client.get('/api/months/2026-09').json()['note'] == ''
