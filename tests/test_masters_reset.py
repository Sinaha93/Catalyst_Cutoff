from copy import deepcopy
from io import BytesIO
import hashlib
import json
import sqlite3

import pytest
from fastapi.testclient import TestClient
from openpyxl import load_workbook

from backend.adapters.storage import Store
from backend.adapters.masters import read_master
from backend.adapters.pricing import read_pricing
from backend.api.app import create_app
from backend.application.basis import Basis
from backend.application.closing import Closing
from backend.application.imports import Imports
from backend.application.masters import Masters, value
from backend.domain.errors import WorkflowError
from test_closing import ready, edit, MONTH, PART
from test_holds import seed


def publish(store, role='route_master', rows=None, start=MONTH, end=None, apply=True):
    m=Masters(store);o=m.overview(MONTH)
    args={'role':role,'effective_from':start,'effective_to':end,'reason':'합성 검증 기준 등록',
          'expected_head':next((v['id'] for v in o['versions'] if v['role']==role),None),
          'rows':rows,'batch_id':None if rows is not None else next(b['id'] for b in o['candidates'] if b['role']==role)}
    p=m.proposal(MONTH,**args)
    result=m.publish(MONTH,store.get(MONTH)['revision'],p['fingerprint'],**args)
    if apply:m.select(MONTH,store.get(MONTH)['revision'],result['version_id'])
    return result['version_id']


def editable(store,vid): return [{'part':r['part'],**value(r)} for r in Masters(store).get(vid)['payload']['records']]


def test_native_route_changes_calculation_and_pins_other_months(tmp_path):
    s=Store(tmp_path);seed(s);m=Masters(s)
    original=Basis(s).preview(MONTH)['rows'][0]
    first=publish(s);publish(s,'bom_master')
    assert Basis(s).preview(MONTH)['rows'][0]['product_quantity']==original['product_quantity']
    s.start('2026-10')
    assert m.overview('2026-10')['selected']['route_master']==first
    rows=editable(s,first);rows[0]['plant']='울산5공장'
    second=publish(s,rows=rows,apply=False)
    assert Basis(s).preview(MONTH)['rows'][0]['plant']==original['plant']
    assert m.compare_selection(MONTH,second)['changes'][0]['after']['plant']=='울산5공장'
    m.select(MONTH,s.get(MONTH)['revision'],second)
    assert Basis(s).preview(MONTH)['rows'][0]['plant']=='울산5공장'
    assert m.overview('2026-10')['selected']['route_master']==first
    s.start('2026-11');assert m.overview('2026-11')['selected']['route_master']==second
    assert m.get(first)['payload']['records'][0]['evidence']['_normalized']['value']['plant']==original['plant']


def test_native_collection_is_used_and_tracking_rows_are_not_double_counted(tmp_path):
    s=Store(tmp_path);seed(s);first=publish(s);rows=editable(s,first)
    rows[0]['metric']='출고/이동처리'
    publish(s,rows=rows)
    changed=Basis(s).preview(MONTH)['rows'][0]
    assert all(e['metric']=='출고/이동처리' for e in changed['stock_evidence'])
    rows.append({**deepcopy(rows[0]),'route_id':'TRACE','included':False})
    publish(s,rows=rows)
    assert Basis(s).preview(MONTH)['route_count']==1


def test_glovis_cannot_be_changed_to_ratio_source(tmp_path):
    s=Store(tmp_path);seed(s);vid=publish(s);rows=editable(s,vid)
    rows[0].update(path='글로비스',destination='현대 글로비스')
    with pytest.raises(WorkflowError,match='실제 입고'):publish(s,rows=rows)
    rows[0].update(source_role='glovis_receipts',metric='실제 입고수량',warehouses=[])
    publish(s,rows=rows)
    assert Basis(s).preview(MONTH)['rows'][0]['status']=='source_missing'


def test_bom_comparison_external_only_and_period_limits(tmp_path):
    s=Store(tmp_path);seed(s);m=Masters(s);vid=publish(s,'bom_master',end=MONTH)
    assert m.get(vid)['payload']['origin']['filename']=='bom_master.xlsx'
    with pytest.raises(WorkflowError,match='적용할 수 없는'):m.select('2026-10',1,vid)
    s.start('2026-10');assert 'bom_master' not in m.overview('2026-10')['selected']
    with pytest.raises(WorkflowError,match='BOM은'):
        m.proposal(MONTH,'bom_master',MONTH,None,'직접 수정 금지',vid,rows=[])
    exported=m.export(vid)
    assert read_master(exported,MONTH,'bom_master')['status']=='ready'


def test_prices_reusable_with_period_and_original_final_frozen(tmp_path):
    s=Store(tmp_path);c=ready(s);v=c.preview(MONTH);snap=c.finalize(MONTH,v['revision'],v['fingerprint'],'master-final-001')
    c.reopen(MONTH,s.get(MONTH)['revision'],'기준 변경 검증')
    edit(c,'prices',None)
    rows=[{'part':PART,'destination':'현대 울산','price':'20','price_kind':'정단가','reason':'단가 승인','basis':'합성 단가표'}]
    vid=publish(s,'price_policy',rows=rows)
    # Price changes can invalidate dependent monthly decisions; re-approve hold.
    from test_holds import line
    edit(c,'hold',{'lines':[line()]})
    assert c.preview(MONTH)['rows'][0]['amount']=='160'
    assert c.snapshot(snap['id'])['payload']['amount_total']=='100'
    s.start('2026-10');assert Masters(s).overview('2026-10')['selected']['price_policy']==vid
    assert read_pricing(Masters(s).export(vid),MONTH,'price_policy')['status']=='ready'


def test_reset_preserves_originals_masters_snapshots_and_rejects_stale_writes(tmp_path):
    s=Store(tmp_path);c=ready(s);vid=publish(s);v=c.preview(MONTH)
    # New evidence labels may invalidate prior scoped edits; refresh explicit hold/price.
    from test_holds import line
    edit(c,'hold',{'lines':[line()]});edit(c,'prices',{'lines':[{'destination':'현대 울산','price':'12.55','price_kind':'가단가'}]})
    v=c.preview(MONTH);snap=c.finalize(MONTH,v['revision'],v['fingerprint'],'reset-final-001')
    with pytest.raises(WorkflowError,match='확정 월'):s.reset_month(MONTH,s.get(MONTH)['revision'],'확정 보호')
    c.reopen(MONTH,s.get(MONTH)['revision'],'다시 작성')
    s.save(MONTH,s.get(MONTH)['revision'],'초안 메모');before=s.get(MONTH)
    originals={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in (tmp_path/'originals').rglob('*') if p.is_file()}
    selected={b['id'] for b in Imports(s).list(MONTH) if b['selected']}
    after=s.reset_month(MONTH,before['revision'],'합성 초기화 검증')
    assert after['id']!=before['id'] and after['revision']>before['revision'] and after['note']==''
    assert Closing(s).history(MONTH)==[] and s.archives(MONTH)[0]['note']=='초안 메모'
    assert Masters(s).overview(MONTH)['selected']['route_master']==vid
    assert {b['id'] for b in Imports(s).list(MONTH) if b['selected']}==selected
    assert c.snapshot(snap['id'])['payload']['amount_total']=='100'
    assert originals=={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in (tmp_path/'originals').rglob('*') if p.is_file()}
    assert 'hold_required' in [i['code'] for i in c.preview(MONTH)['rows'][0]['issues']]
    with pytest.raises(WorkflowError):s.save(MONTH,before['revision'],'낡은 화면')
    with pytest.raises(WorkflowError):s.reset_month(MONTH,before['revision'],'중복 재시도')
    with s.connect() as conn: assert conn.execute('SELECT count(*) FROM monthly_decision WHERE draft_id=?',(before['id'],)).fetchone()[0]>0


def test_publish_compare_and_conflict_are_atomic(tmp_path):
    s=Store(tmp_path);seed(s);vid=publish(s);m=Masters(s);rows=editable(s,vid)
    args=dict(role='route_master',effective_from=MONTH,effective_to=None,reason='동시 수정',expected_head=vid,rows=rows)
    p=m.proposal(MONTH,**args);before=s.get(MONTH)
    with pytest.raises(WorkflowError):m.publish(MONTH,before['revision'],'0'*64,**args)
    assert s.get(MONTH)==before
    publish(s,rows=rows)
    with pytest.raises(WorkflowError):m.publish(MONTH,s.get(MONTH)['revision'],p['fingerprint'],**args)
    with s.connect(write=True) as conn:
        with pytest.raises(sqlite3.IntegrityError):conn.execute('DELETE FROM master_version WHERE id=?',(vid,))


def test_route_export_roundtrip_retains_collection_and_split_routes(tmp_path):
    s=Store(tmp_path);seed(s);vid=publish(s);rows=editable(s,vid)
    rows.append({**rows[0],'route_id':'SECOND','plant':'울산1'})
    vid=publish(s,rows=rows);m=Masters(s);data=m.export(vid)
    parsed=read_master(data,MONTH,'route_master')
    assert parsed['status']=='ready'
    assert all(value(r)['warehouses']==['세종공업(화성)'] for r in parsed['records'])
    assert Basis(s).preview(MONTH)['status_counts']=={'factory_quantities_needed':2}
    wb=load_workbook(BytesIO(data));assert wb.active.freeze_panes is None;wb.close()


def test_api_reset_and_master_session_checks(tmp_path):
    with TestClient(create_app(tmp_path),base_url='http://127.0.0.1') as client:
        token=client.get('/api/session').json()['token'];h={'Origin':'http://127.0.0.1','X-Session-Token':token}
        client.post('/api/months',headers=h,json={'month':MONTH})
        body={'expected_revision':1,'reason':'합성 UI 초기화'}
        assert client.post(f'/api/months/{MONTH}/reset',json=body).status_code==403
        assert client.post(f'/api/months/{MONTH}/reset',headers=h,json=body).status_code==200
        assert len(client.get(f'/api/months/{MONTH}/archives').json())==1
        assert client.get(f'/api/months/{MONTH}/masters').json()['selected']=={}


def test_migrate_v4_backs_up_and_retains_data(tmp_path):
    s=Store(tmp_path);seed(s)
    with s.connect(write=True) as conn:
        conn.execute('DROP TABLE draft_master');conn.execute('DROP TABLE master_version');conn.execute('PRAGMA user_version=4')
    before=s.get(MONTH);s.initialize()
    assert s.get(MONTH)==before
    backups=list((tmp_path/'backups').glob('before-schema-5-*.sqlite'));assert backups
    with sqlite3.connect(backups[0]) as conn:assert conn.execute('PRAGMA user_version').fetchone()[0]==4


def test_unrelated_native_row_does_not_invalidate_unchanged_part(tmp_path):
    s=Store(tmp_path);seed(s);vid=publish(s)
    before=Basis(s).preview(MONTH)['part_fingerprints'][PART]
    rows=editable(s,vid);rows.append({**rows[0],'route_id':'OTHER','part':'H99999-AA001'})
    publish(s,rows=rows)
    assert Basis(s).preview(MONTH)['part_fingerprints'][PART]==before


def test_registered_master_cannot_be_bypassed_by_excel_selection(tmp_path):
    s=Store(tmp_path);seed(s);publish(s)
    b=next(b for b in Imports(s).list(MONTH) if b['role']=='route_master')
    with pytest.raises(WorkflowError,match='프로그램 기준'):
        Imports(s).select(MONTH,b['id'],s.get(MONTH)['revision'],b['id'])


def test_duplicate_bom_rows_are_preserved_and_compared(tmp_path):
    from test_basis import bom_book,content
    s=Store(tmp_path);seed(s);vid=publish(s,'bom_master');w=bom_book()
    w.active.append([c.value for c in w.active[2]])
    imp=Imports(s);r=imp.register(MONTH,'bom_master',MONTH,'duplicate-bom.xlsx',s.get(MONTH)['revision'],content(w),period_confirmed=True)
    m=Masters(s);p=m.proposal(MONTH,'bom_master',MONTH,None,'동일 구성 원본행 보존',vid,batch_id=r['batch']['id'])
    assert len(p['payload']['records'])==4 and len(p['changes'])==1
