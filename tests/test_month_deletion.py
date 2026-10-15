import pytest
from backend.adapters.storage import Store
from backend.application.closing import Closing
from backend.application.exports import Exports
from backend.application.masters import Masters
from backend.domain.errors import WorkflowError
from test_closing import ready, MONTH
from test_masters_reset import publish


def test_delete_finalized_month_removes_history_originals_and_exports(tmp_path):
    s=Store(tmp_path);c=ready(s);v=c.preview(MONTH)
    snap=c.finalize(MONTH,v['revision'],v['fingerprint'],'delete-test')
    ex=Exports(s);output=ex.create(snap['id']);path=ex.file(output['id'])
    with s.connect() as conn:originals=[s.root/r[0] for r in conn.execute('SELECT relative_path FROM source_file')]
    old=s.get(MONTH);s.delete_month(MONTH,old['revision'])
    assert s.list()==[] and not path.exists() and all(not p.exists() for p in originals)
    with s.connect() as conn:
        for table in ('closing_month','draft','closing_snapshot','audit_event','source_file','source_record','import_batch','export_run'):
            assert conn.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0]==0
        assert conn.execute("SELECT 1 FROM sqlite_master WHERE name='immutable_closing_delete'").fetchone()
        assert conn.execute('PRAGMA foreign_key_check').fetchall()==[]
    fresh=s.start(MONTH);assert fresh['id']!=old['id'] and fresh['note']=='' and fresh['revision']==1


def test_delete_preserves_shared_program_masters_and_rejects_referenced_snapshot(tmp_path):
    s=Store(tmp_path);c=ready(s);publish(s);publish(s,'bom_master');v=c.preview(MONTH)
    # Master selection can make old monthly decisions require review; refresh them.
    from test_closing import edit
    from test_holds import line
    edit(c,'hold',{'lines':[line()]});edit(c,'prices',{'lines':[{'destination':'현대 울산','price':'12.55','price_kind':'가단가'}]})
    v=c.preview(MONTH);snap=c.finalize(MONTH,v['revision'],v['fingerprint'],'delete-shared')
    old=s.get(MONTH);d=s.start('2026-10');c.link_carry('2026-10',d['revision'],snap['id'])
    with pytest.raises(WorkflowError) as e:s.delete_month(MONTH,old['revision'])
    assert e.value.code=='MONTH_IN_USE' and s.get(MONTH)==old
    with s.connect() as conn:assert conn.execute("SELECT 1 FROM sqlite_master WHERE name='immutable_closing_delete'").fetchone()
    s.delete_month('2026-10',s.get('2026-10')['revision'])
    s.delete_month(MONTH,old['revision'])
    assert len(Masters(s).overview(s.start('2026-10')['month'])['versions'])==2
    assert Masters(s).effective('2026-10',{})['bom_master']['records']


def test_delete_stale_revision_and_rollback_keeps_other_month(tmp_path):
    s=Store(tmp_path);s.initialize();d=s.start(MONTH);s.save(MONTH,d['revision'],'새 메모');other=s.start('2026-10')
    with pytest.raises(WorkflowError):s.delete_month(MONTH,d['revision'])
    assert s.get(MONTH)['note']=='새 메모'
    with s.connect(write=True) as conn:conn.execute("CREATE TRIGGER fail_delete BEFORE DELETE ON closing_month BEGIN SELECT RAISE(ABORT,'test rollback'); END")
    import sqlite3
    with pytest.raises(sqlite3.IntegrityError):s.delete_month(MONTH,s.get(MONTH)['revision'])
    assert s.get('2026-10')==other and s.get(MONTH)['note']=='새 메모'
    with s.connect() as conn:assert conn.execute("SELECT 1 FROM sqlite_master WHERE name='immutable_closing_delete'").fetchone()
