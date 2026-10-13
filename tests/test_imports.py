from datetime import datetime
from io import BytesIO
import hashlib
import json
import sqlite3

import openpyxl
import pytest
from fastapi.testclient import TestClient

from backend.adapters.heesung import read_shipments
from backend.adapters.storage import Store, SCHEMA
from backend.application.imports import Imports
from backend.domain.errors import WorkflowError
from backend.api.app import create_app


def workbook(rows=None, reordered=False, formula=False):
    book=openpyxl.Workbook();sheet=book.active;sheet.title='출하 근거'
    headers=['자동차품번','출하','년월','출하(합계)']
    rows=rows if rows is not None else [['99999-AA001',10,datetime(2026,9,1),10],['99999-AA001',-2,datetime(2026,9,1),-2],['99999-AA002',0,datetime(2026,9,1),0]]
    if reordered:
        sheet.append(['제목 행']);sheet.append(['자료 안내'])
        order=[2,3,0,1];sheet.append([headers[i] for i in order])
        for r in rows:sheet.append([r[i] for i in order])
    else:
        sheet.append(headers)
        for r in rows:sheet.append(r)
    if formula:sheet['B2']='=5+5'
    stream=BytesIO();book.save(stream);return stream.getvalue()


@pytest.fixture
def store(tmp_path):
    s=Store(tmp_path/'자료');s.initialize();s.start('2026-09');return s


def test_headers_move_negative_zero_and_duplicate_part_evidence():
    result=read_shipments(workbook(reordered=True),'2026-09')
    assert result['status']=='ready'
    assert result['summary']['quantity_total']=='8'
    assert result['summary']['part_count']==2
    assert result['summary']['row_count']==3
    assert result['records'][0]['row_number']==4
    assert result['records'][0]['evidence']['D4']['value']==10
    assert result['records'][2]['quantity']=='0'


def test_formula_without_cache_is_not_zero_and_bad_period_not_ready():
    r=read_shipments(workbook(formula=True),'2026-08')
    assert r['status']=='needs_review'
    assert r['records'][0]['quantity'] is None
    assert r['records'][0]['evidence']['B2']['formula']=='=5+5'
    assert {'PERIOD_MISMATCH','QUANTITY_UNAVAILABLE'} <= {i['code'] for i in r['issues']}


def test_unknown_header_and_invalid_part_are_review_not_empty_success():
    r=read_shipments(workbook([['bad part',3,datetime(2026,9,1),3]]),'2026-09')
    assert r['status']=='needs_review' and len(r['records'])==1
    book=openpyxl.Workbook();book.active.append(['새 양식','임의 수량']);b=BytesIO();book.save(b)
    assert read_shipments(b.getvalue(),'2026-09')['status']=='needs_review'


def register(service,content=None,revision=1):
    return service.register('2026-09','heesung_shipments','2026-09','출하.xlsx',revision,content or workbook())


def test_copy_idempotency_selection_replacement_and_history(store):
    service=Imports(store);data=workbook();first=register(service,data)
    assert first['draft']['revision']==2
    path,_=service.original('2026-09',first['batch']['id'])
    assert path.read_bytes()==data
    duplicate=register(service,data,2)
    assert duplicate['duplicate'] and duplicate['draft']['revision']==2
    selected=service.select('2026-09',first['batch']['id'],2,None)
    assert selected['revision']==3
    second=register(service,workbook([['99999-AA001',14,datetime(2026,9,1),14]]),3)
    assert [x['id'] for x in service.list('2026-09') if x['selected']]==[first['batch']['id']]
    with pytest.raises(WorkflowError):service.select('2026-09',second['batch']['id'],4,None)
    service.select('2026-09',second['batch']['id'],4,first['batch']['id'])
    assert [x['id'] for x in service.list('2026-09') if x['selected']]==[second['batch']['id']]
    assert service.original('2026-09',first['batch']['id'])[0].read_bytes()==data
    with store.connect() as conn:
        assert conn.execute('select count(*) from source_selection_event').fetchone()[0]==2
        assert conn.execute('select count(*) from source_file').fetchone()[0]==2


def test_audit_failure_registration_rolls_back_and_retry_reuses_file(store):
    service=Imports(store);data=workbook()
    with store.connect(write=True) as conn:
        conn.execute("CREATE TRIGGER fail_import_audit BEFORE INSERT ON audit_event BEGIN SELECT RAISE(ABORT,'failure'); END")
    with pytest.raises(sqlite3.IntegrityError):register(service,data)
    assert service.list('2026-09')==[] and store.get('2026-09')['revision']==1
    assert len(list((store.root/'originals').rglob('source.xlsx')))==1
    with store.connect(write=True) as conn:conn.execute('DROP TRIGGER fail_import_audit')
    register(service,data)
    assert len(list((store.root/'originals').rglob('source.xlsx')))==1


def pdf_result():
    return {'status':'needs_review','issues':[],'summary':{'row_count':2,'part_count':2,'quantity_total':'10','printed_total':'10','period_confirmed':False},
            'records':[{'sheet':'PDF 1페이지','row_number':i+1,'part':p,'quantity':q,'evidence':{'pdf':{'box':[0,.1+i*.1,1,.2+i*.1],'ocr_part':p,'ocr_quantity':q,'peer_quantity':q,'reviewed':False}}} for i,(p,q) in enumerate([('99999-AA001','7'),('99999-AA002','3')])]}


def test_pdf_pending_and_failed_replacement_keeps_selected(store,monkeypatch):
    monkeypatch.setattr('backend.application.imports.read_carryover',lambda *_:pdf_result())
    service=Imports(store);first=register(service)
    service.select('2026-09',first['batch']['id'],2,None)
    pdf=service.register('2026-09','heesung_carryover','2026-08','재고.pdf',3,b'%PDF-1.4\nreference')
    assert pdf['batch']['status']=='needs_review'
    with pytest.raises(WorkflowError):service.select('2026-09',pdf['batch']['id'],4,None)
    bad=register(service,workbook(formula=True),4)
    with pytest.raises(WorkflowError):service.select('2026-09',bad['batch']['id'],5,first['batch']['id'])
    assert [x['id'] for x in service.list('2026-09') if x['selected']]==[first['batch']['id']]


def test_pdf_review_checks_sum_rows_and_preserves_adopted_evidence(store,monkeypatch):
    monkeypatch.setattr('backend.application.imports.read_carryover',lambda *_:pdf_result())
    service=Imports(store)
    batch=service.register('2026-09','heesung_carryover','2026-08','재고.pdf',1,b'%PDF-test')['batch']
    bid=batch['id'];rows=[{'ordinal':i,'part':p,'quantity':q,'peer_quantity':q,'reviewed':True} for i,(p,q) in enumerate([('99999-AA001','7'),('99999-AA002','3')])]
    with pytest.raises(WorkflowError):service.review_pdf('2026-09',bid,2,rows[:1],'10','2026-08','원본 확인')
    checked=service.review_pdf('2026-09',bid,2,rows,'11','2026-08','표시 합계 확인')
    assert checked['batch']['status']=='needs_review'
    with pytest.raises(WorkflowError):service.select('2026-09',bid,3,None)
    checked=service.review_pdf('2026-09',bid,3,rows,'10','2026-08','원본과 대조')
    assert checked['batch']['status']=='ready'
    service.select('2026-09',bid,4,None)
    rows[0]['quantity']=rows[0]['peer_quantity']='8'
    revised=service.review_pdf('2026-09',bid,5,rows,'11','2026-08','재확인 후 인식 정정')
    assert revised['batch']['id']!=bid
    assert service.detail('2026-09',bid)['records'][0]['quantity']=='7'
    assert [s['id'] for s in service.list('2026-09') if s['selected']]==[bid]
    assert revised['batch']['records'][0]['evidence']['pdf']['ocr_quantity']=='7'
    with store.connect() as conn:assert conn.execute('select count(*) from source_review').fetchone()[0]==3


def test_corrupt_original_and_stale_revision_are_rejected(store):
    service=Imports(store);first=register(service)
    with pytest.raises(WorkflowError):register(service,revision=1)
    path,_=service.original('2026-09',first['batch']['id']);path.write_bytes(b'changed')
    with pytest.raises(WorkflowError) as error:service.select('2026-09',first['batch']['id'],2,None)
    assert error.value.code=='ORIGINAL_CHANGED'
    assert not any(s['selected'] for s in service.list('2026-09'))


def test_reread_is_new_candidate_without_duplicate_physical_file(store):
    service=Imports(store);first=register(service)
    service.select('2026-09',first['batch']['id'],2,None)
    reread=service.reread('2026-09',first['batch']['id'],3)
    assert reread['batch']['id']!=first['batch']['id']
    assert [s['id'] for s in service.list('2026-09') if s['selected']]==[first['batch']['id']]
    with store.connect() as conn:
        assert conn.execute('select count(*) from source_file').fetchone()[0]==1
        assert conn.execute('select count(*) from import_batch').fetchone()[0]==2


def test_v1_migration_preserves_draft_and_creates_backup(tmp_path):
    store=Store(tmp_path);store.path.parent.mkdir()
    with sqlite3.connect(store.path) as conn:
        for sql in SCHEMA:conn.execute(sql)
        conn.execute('pragma user_version=1')
    old=store.start('2026-09');store.save('2026-09',1,'이전 버전의 메모')
    store.initialize()
    assert store.get('2026-09')['id']==old['id']
    assert store.get('2026-09')['note']=='이전 버전의 메모'
    backups=list((tmp_path/'backups').glob('*.sqlite'));assert len(backups)==1
    with sqlite3.connect(backups[0]) as conn:
        assert conn.execute('pragma user_version').fetchone()[0]==1
        assert conn.execute('select note from draft').fetchone()[0]=='이전 버전의 메모'


def test_upload_api_and_restart_evidence(tmp_path):
    data=workbook()
    with TestClient(create_app(tmp_path),base_url='http://127.0.0.1') as c:
        h={'Origin':'http://127.0.0.1','X-Session-Token':c.get('/api/session').json()['token']}
        c.post('/api/months',json={'month':'2026-09'},headers=h)
        params={'role':'heesung_shipments','source_period':'2026-09','filename':'../출하.xlsx','expected_revision':1}
        url='/api/months/2026-09/sources'
        assert c.post(url,params=params,content=data).status_code==403
        response=c.post(url,params=params,content=data,headers=h);assert response.status_code==200
        batch=response.json()['batch'];bid=batch['id'];assert batch['filename']=='출하.xlsx'
        downloaded=c.get(f'{url}/{bid}/original');assert hashlib.sha256(downloaded.content).digest()==hashlib.sha256(data).digest()
    with TestClient(create_app(tmp_path),base_url='http://127.0.0.1') as c:
        detail=c.get(f'/api/months/2026-09/sources/{bid}').json()
        assert len(detail['records'])==3
        assert detail['records'][1]['quantity']=='-2'
        assert c.get(f'/api/months/2026-08/sources/{bid}').status_code==404
