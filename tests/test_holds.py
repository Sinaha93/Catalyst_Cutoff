from datetime import datetime
import sqlite3
from unittest.mock import patch

import openpyxl
import pytest
from fastapi.testclient import TestClient

from backend.adapters.storage import Store, SCHEMA, IMPORT_SCHEMA
from backend.application.holds import Holds, validate_lines
from backend.application.allocation import Allocation
from backend.application.imports import Imports
from backend.api.app import create_app
from backend.domain.errors import WorkflowError
from test_basis import bom_book, route_book, content
from test_erp import stock_book
from test_imports import workbook
from test_reconciliation import book as report_book


def context():
    return {'eligible':True,'opening_by_destination':{'현대 울산':'3'},'destinations':['현대 울산','기아 화성'],'incoming':'7','available':'10'}


def line(**changes):
    return {'destination':'현대 울산','new_hold':'1','released':'2','reason':'일부 정산 조건 해소','evidence':'가상 전표 17호',**changes}


@pytest.mark.parametrize('released,new_hold,action,remaining',[
    ('0','0','보류 계속','3'),('1','0','일부 해소','2'),('3','0','전부 해소','0'),('3','2','전부 해소 + 신규 보류','2')])
def test_hold_actions_and_conservation(released,new_hold,action,remaining):
    r=validate_lines(context(),[line(released=released,new_hold=new_hold)])
    assert r['held']==remaining and r['lines'][0]['action']==action


@pytest.mark.parametrize('changes,code',[
    ({'released':'4'},'HOLD_RELEASE_EXCEEDS'),({'new_hold':'8'},'HOLD_NEW_EXCEEDS'),
    ({'new_hold':''},'HOLD_QUANTITY'),({'released':'-1'},'HOLD_QUANTITY'),({'new_hold':'1.5'},'HOLD_QUANTITY'),
    ({'new_hold':True},'HOLD_QUANTITY'),({'reason':' '},'HOLD_EVIDENCE_REQUIRED'),
    ({'evidence':''},'HOLD_EVIDENCE_REQUIRED'),({'destination':'임의공장'},'HOLD_DESTINATION')])
def test_invalid_decision_not_saved(changes,code):
    with pytest.raises(WorkflowError) as e:validate_lines(context(),[line(**changes)])
    assert e.value.code==code


def test_no_hold_requires_explicit_zero_and_unresolved_sources_block():
    c=context();c['opening_by_destination']={}
    assert validate_lines(c,[line(new_hold='0',released='0')])['lines'][0]['action']=='보류 없음'
    c['eligible']=False
    with pytest.raises(WorkflowError) as e:validate_lines(c,[line(new_hold='0',released='0')])
    assert e.value.code=='HOLD_SOURCE_REVIEW'


def test_duplicate_destinations_and_missing_opening_are_not_silently_summed():
    with pytest.raises(WorkflowError) as e:validate_lines(context(),[line(),line()])
    assert e.value.code=='HOLD_DESTINATION'
    with pytest.raises(WorkflowError) as e:validate_lines(context(),[line(destination='기아 화성',released='0')])
    assert e.value.code=='HOLD_OPENING_MISSING'


def seed(store):
    """Synthetic values only; also used by the browser integration test."""
    store.initialize();store.start('2026-09');imports=Imports(store)
    route=route_book();route.active.delete_rows(3)
    stock=stock_book();stock.active['B5']='세종공업(화성)'
    report=report_book();report.active['E4']='99998-AA001'
    erp=openpyxl.Workbook();s=erp.active
    s.append(['품목자산분류','품명','품번','합계','현대 울산'])
    s.append(['품목자산분류','품명','품번','수량계','수량'])
    s.append(['TOTAL',None,None,7,7]);s.append(['4.촉매,귀금속','CATALYST','R60099998-AA001',7,7])
    fixtures=[('bom_master',content(bom_book())),('route_master',content(route)),('product_stock',content(stock)),
              ('heesung_shipments',workbook([['99998-AA001',7,datetime(2026,9,1),7]])),('erp_receipts',content(erp)),('comparison_report',content(report))]
    for role,data in fixtures:
        r=imports.register('2026-09',role,'2026-09',role+'.xlsx',store.get('2026-09')['revision'],data,period_confirmed=True)
        assert r['batch']['status']=='ready',r['batch']['result']
        imports.select('2026-09',r['batch']['id'],store.get('2026-09')['revision'],None)
    fake={'status':'ready','issues':[],'summary':{'period_confirmed':True},'records':[{'part':'99998-AA001','quantity':'3','sheet':'PDF 1페이지','row_number':1,'evidence':{'pdf':{'peer_quantity':'3'}}}]}
    with patch('backend.application.imports.read_carryover',return_value=fake):
        r=imports.register('2026-09','heesung_carryover','2026-08','검증용.pdf',store.get('2026-09')['revision'],b'%PDF-test-only',period_confirmed=True)
        imports.select('2026-09',r['batch']['id'],store.get('2026-09')['revision'],None)


def test_persistence_supersession_and_automatic_allocation(tmp_path):
    store=Store(tmp_path);seed(store);holds=Holds(store);p=holds.preview('2026-09')
    assert p['rows'][0]['historical_held']=='4' and p['rows'][0]['opening_by_destination']=={'현대 울산':'3'}
    first=holds.save('2026-09','99998-AA001',p['revision'],p['input_fingerprint'],[line()])
    assert first['held']=='2'
    allocation=Allocation(store).preview('2026-09')['rows'][0]
    assert allocation['status']=='ready' and allocation['closing_total']=='8' and allocation['held']=='2'
    assert allocation['pool']['hold_decision']['id']==first['decision_id']
    holds=Holds(Store(tmp_path));p=holds.preview('2026-09')
    holds.save('2026-09','99998-AA001',p['revision'],p['input_fingerprint'],[line(new_hold='0',released='3')])
    history=holds.history('2026-09');assert len(history)==2
    assert history[0]['payload']['supersedes']==first['decision_id'] and history[1]['payload']['held']=='2'
    assert Allocation(store).preview('2026-09')['rows'][0]['closing_total']=='10'


def test_revision_conflict_and_wrong_fingerprint_leave_history_unchanged(tmp_path):
    store=Store(tmp_path);seed(store);holds=Holds(store);p=holds.preview('2026-09')
    with pytest.raises(WorkflowError) as e:holds.save('2026-09','99998-AA001',p['revision'],'f'*64,[line()])
    assert e.value.code=='HOLD_BASIS_CHANGED' and holds.history('2026-09')==[]
    store.save('2026-09',p['revision'],'another tab')
    with pytest.raises(WorkflowError) as e:holds.save('2026-09','99998-AA001',p['revision'],p['input_fingerprint'],[line()])
    assert e.value.code=='REVISION_CONFLICT' and holds.history('2026-09')==[]


def test_identical_reread_preserves_hold_and_history(tmp_path):
    store=Store(tmp_path);seed(store);holds=Holds(store);p=holds.preview('2026-09')
    holds.save('2026-09','99998-AA001',p['revision'],p['input_fingerprint'],[line()])
    imports=Imports(store);old=next(b for b in imports.list('2026-09') if b['role']=='product_stock' and b['selected'])
    candidate=imports.reread('2026-09',old['id'],store.get('2026-09')['revision'])
    imports.select('2026-09',candidate['batch']['id'],store.get('2026-09')['revision'],old['id'])
    assert holds.preview('2026-09')['rows'][0]['decision_status']=='current'
    row=Allocation(store).preview('2026-09')['rows'][0]
    assert row['status']=='ready' and row['closing_total']=='8'
    assert len(holds.history('2026-09'))==1


def test_mutation_api_requires_session_and_saves_validated_lines(tmp_path):
    seed(Store(tmp_path))
    with TestClient(create_app(tmp_path),base_url='http://127.0.0.1') as client:
        p=client.get('/api/months/2026-09/holds').json()
        body={'expected_revision':p['revision'],'fingerprint':p['input_fingerprint'],'lines':[line()]}
        assert client.post('/api/months/2026-09/holds/99998-AA001',json=body).status_code==403
        headers={'Origin':'http://127.0.0.1','X-Session-Token':client.get('/api/session').json()['token']}
        r=client.post('/api/months/2026-09/holds/99998-AA001',json=body,headers=headers);assert r.status_code==200
        assert client.get('/api/months/2026-09/allocation').json()['rows'][0]['closing_total']=='8'


def test_manual_pool_and_saved_hold_are_not_combined_or_silently_overwritten(tmp_path):
    from test_allocation import input_book
    from backend.application.basis import Basis
    store=Store(tmp_path);seed(store);holds=Holds(store);p=holds.preview('2026-09')
    holds.save('2026-09','99998-AA001',p['revision'],p['input_fingerprint'],[line()])
    imports=Imports(store);w=input_book(Basis(store).preview('2026-09')['input_fingerprint'])
    result=imports.register('2026-09','allocation_inputs','2026-09','과거수량입력.xlsx',store.get('2026-09')['revision'],content(w),period_confirmed=True)
    imports.select('2026-09',result['batch']['id'],store.get('2026-09')['revision'],None)
    row=Allocation(store).preview('2026-09')['rows'][0]
    assert row['status']=='pool_input_conflict' and row['closing_total'] is None and row['destinations']==[]


def test_v2_migration_backups_source_data_and_is_idempotent(tmp_path):
    store=Store(tmp_path);store.path.parent.mkdir(parents=True)
    with sqlite3.connect(store.path) as conn:
        for sql in SCHEMA+IMPORT_SCHEMA:conn.execute(sql)
        conn.execute('PRAGMA user_version=2')
    store.start('2026-09');store.save('2026-09',1,'기존 저장본')
    store.initialize();store.initialize()
    assert store.get('2026-09')['note']=='기존 저장본'
    backups=list((tmp_path/'backups').glob('*.sqlite'));assert len(backups)==1
    with sqlite3.connect(backups[0]) as conn:assert conn.execute('PRAGMA user_version').fetchone()[0]==2
    with store.connect() as conn:
        assert conn.execute('PRAGMA user_version').fetchone()[0]==5
        assert conn.execute('SELECT count(*) FROM hold_decision').fetchone()[0]==0
