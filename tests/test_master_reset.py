from pathlib import Path
from io import BytesIO
import sqlite3
import pytest
from fastapi.testclient import TestClient
from backend.adapters.storage import Store
from backend.application.master_reset import MasterReset,LABELS
from backend.application.masters import Masters
from backend.application.imports import Imports
from backend.application.closing import Closing
from backend.api.app import create_app
from backend.domain.errors import WorkflowError
from test_holds import seed
from test_closing import ready,MONTH
from test_masters_reset import publish
from test_basis import bom_book,route_book,content
from test_pricing import price_book


def reset(s,role='bom_master'):
    service=MasterReset(s);v=service.preview(MONTH,role)
    return service.reset(MONTH,role,v['revision'],v['fingerprint'],v['label']+' 초기화')


@pytest.mark.parametrize('role',['bom_master','route_master','price_master'])
def test_reset_one_master_family_and_reregister(tmp_path,role):
    s=Store(tmp_path);seed(s);imp=Imports(s)
    if role=='price_master':
        r=imp.register(MONTH,role,MONTH,'base.xlsx',s.get(MONTH)['revision'],content(price_book()),period_confirmed=True)
        imp.select(MONTH,r['batch']['id'],s.get(MONTH)['revision'],None)
    vid=publish(s,role);raw=next(b for b in imp.list(MONTH) if b['role']==role)
    path,_=imp.original(MONTH,raw['id']);data=path.read_bytes()
    other={b['role']:b['id'] for b in imp.list(MONTH) if b['selected'] and b['role']!=role}
    before=s.get(MONTH);v=MasterReset(s).preview(MONTH,role)
    assert v['version_count']==1 and not v['blocked']
    assert s.get(MONTH)==before
    result=reset(s,role);assert result['draft']['revision']==before['revision']+1
    assert not [v for v in Masters(s).overview(MONTH)['versions'] if v['role']==role]
    assert not [b for b in imp.list(MONTH) if b['role']==role]
    assert role not in imp.effective_sources(MONTH)
    assert {b['role']:b['id'] for b in imp.list(MONTH) if b['selected']}==other
    assert not path.exists()
    # Identical content can be registered anew after the role reset.
    imp.register(MONTH,role,MONTH,'again.xlsx',s.get(MONTH)['revision'],data,period_confirmed=True)
    fresh=publish(s,role);assert Masters(s).get(fresh)['version']==1
    with s.connect(write=True) as conn:
        with pytest.raises(sqlite3.IntegrityError):conn.execute('DELETE FROM master_version WHERE id=?',(fresh,))


def test_reset_protects_other_active_month_and_finals(tmp_path):
    s=Store(tmp_path);seed(s);vid=publish(s,'bom_master');s.start('2026-10')
    before=s.get(MONTH);v=MasterReset(s).preview(MONTH,'bom_master')
    assert v['blocked']==['2026-10 작업에서 사용 중']
    with pytest.raises(WorkflowError,match='사용 중'):reset(s)
    assert s.get(MONTH)==before and Masters(s).get(vid)


def test_reset_protects_final_even_after_reopen(tmp_path):
    s=Store(tmp_path);c=ready(s);v=c.preview(MONTH)
    snap=c.finalize(MONTH,v['revision'],v['fingerprint'],'reset-protected-final')
    c.reopen(MONTH,s.get(MONTH)['revision'],'기준 초기화 확인')
    with pytest.raises(WorkflowError,match='확정'):reset(s)
    assert c.snapshot(snap['id'])['payload']['amount_total']=='100'


def test_reset_confirmation_and_stale_state_are_atomic(tmp_path):
    s=Store(tmp_path);seed(s);vid=publish(s,'bom_master');m=MasterReset(s);v=m.preview(MONTH,'bom_master')
    with pytest.raises(WorkflowError,match='확인'):m.reset(MONTH,'bom_master',v['revision'],v['fingerprint'],'')
    assert Masters(s).get(vid)
    publish(s,'bom_master')
    with pytest.raises(WorkflowError):m.reset(MONTH,'bom_master',v['revision'],v['fingerprint'],'BOM 초기화')
    with pytest.raises(WorkflowError,match='다시 확인'):m.reset(MONTH,'bom_master',s.get(MONTH)['revision'],v['fingerprint'],'BOM 초기화')
    with pytest.raises(WorkflowError):m.preview(MONTH,'plan_master')
    assert len([x for x in Masters(s).overview(MONTH)['versions'] if x['role']=='bom_master'])==2


def test_reset_preserves_shared_original_file(tmp_path):
    s=Store(tmp_path);s.initialize();s.start(MONTH);imp=Imports(s)
    book=bom_book();routes=route_book();sheet=book.create_sheet('경로')
    for row in routes.active.values:sheet.append(row)
    routes.close();data=content(book)
    for role in ('bom_master','route_master'):
        r=imp.register(MONTH,role,MONTH,'combined.xlsx',s.get(MONTH)['revision'],data,period_confirmed=True)
        imp.select(MONTH,r['batch']['id'],s.get(MONTH)['revision'],None)
    publish(s,'bom_master');publish(s,'route_master')
    route=next(b for b in imp.list(MONTH) if b['role']=='route_master');p=imp.original(MONTH,route['id'])[0]
    result=reset(s)
    assert result['deleted_file_count']==0 and p.read_bytes()==data
    assert imp.effective_sources(MONTH)['route_master']['records']


def test_invalid_file_path_rolls_back(tmp_path):
    s=Store(tmp_path);seed(s);vid=publish(s,'bom_master')
    with s.connect(write=True) as conn:
        conn.execute("UPDATE source_file SET relative_path='../outside.xlsx' WHERE id=(SELECT file_id FROM import_batch WHERE role='bom_master' LIMIT 1)")
    before=s.get(MONTH)
    with pytest.raises(WorkflowError,match='경로'):reset(s)
    assert s.get(MONTH)==before and Masters(s).get(vid)


def test_reset_api_requires_session_and_confirmation(tmp_path):
    s=Store(tmp_path);seed(s);publish(s,'bom_master')
    with TestClient(create_app(tmp_path),base_url='http://127.0.0.1') as client:
        p=client.get(f'/api/months/{MONTH}/masters/reset-preview?role=bom_master').json()
        body={'role':'bom_master','expected_revision':p['revision'],'fingerprint':p['fingerprint'],'confirmation':'BOM 초기화'}
        assert client.post(f'/api/months/{MONTH}/masters/reset',json=body).status_code==403
        token=client.get('/api/session').json()['token'];headers={'Origin':'http://127.0.0.1','X-Session-Token':token}
        assert client.post(f'/api/months/{MONTH}/masters/reset',json={**body,'confirmation':''},headers=headers).status_code!=200
        assert client.post(f'/api/months/{MONTH}/masters/reset',json=body,headers=headers).status_code==200
        assert not client.get(f'/api/months/{MONTH}/masters').json()['selected'].get('bom_master')
