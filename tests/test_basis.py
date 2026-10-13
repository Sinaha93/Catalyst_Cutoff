from copy import deepcopy
from io import BytesIO

import openpyxl
import pytest
from fastapi.testclient import TestClient

from backend.adapters.masters import read_master
from backend.adapters.storage import Store
from backend.application.basis import Basis, link
from backend.application.imports import Imports
from backend.domain.errors import WorkflowError


def content(w):
    stream = BytesIO(); w.save(stream); w.close(); return stream.getvalue()


def bom_book():
    w = openpyxl.Workbook();s = w.active
    s.append(['제품부번', '고객사', '촉매사', '촉매사용구분'] + [f'촉매{i}{k}' for i in range(1,5) for k in ('부번','소요량')])
    s.append(['M99999-AA001', '고객 A', '희성', '사용', 'R60099998-AA001', 2])
    s.append(['M99999-AA001', '고객 B', '희성', '사용', 'R60099998-AA001', 2])
    s.append(['H99999-AA001', '고객 A', '희성', '미사용', None, 0])
    return w


def route_book():
    w = openpyxl.Workbook();s=w.active
    s.append(['번호','촉매사','제품 품번','납품 경로 / 경유지','공장 / 마감 표시','ERP 마감처','처리 상태','반영한 내용'])
    s.append(['R1','희성','M99999-AA001','세종공업','공장 A','현대 울산','설정 완료',None])
    s.append(['R2','희성','M99999-AA001','포레시아 장안','공장 B','기아 화성','설정 완료',None])
    return w


def batch(role, result):
    return {'id':role, 'filename':role+'.xlsx', 'records':[dict(r,ordinal=i) for i,r in enumerate(result['records'])]}


def stock_row(ordinal, warehouse, part='M99999-AA001', quantity='12', **extra):
    return {'ordinal':ordinal,'sheet':'수불','row_number':ordinal+5,'part':part,'quantity':None,
            'evidence':{'_normalized':{'value':{'warehouse':warehouse,'metrics':{'입고/이동처리':quantity,'출고/이동처리':'99','이월수량':'87',**extra}}}}}


def sources():
    return {'bom_master':batch('bom_master',read_master(content(bom_book()),'2026-09','bom_master')),
            'route_master':batch('route_master',read_master(content(route_book()),'2026-09','route_master')),
            'product_stock':{'id':'stock','filename':'수불.xlsx','records':[stock_row(0,'세종공업(화성)'),stock_row(1,'포레시아-장안',quantity='8')]}}


def test_bom_duplicate_customers_single_composition_and_keep_m_h_separate():
    r = read_master(content(bom_book()),'2026-09','bom_master')
    assert r['status']=='ready' and r['summary']['row_count']==3 and r['summary']['part_count']==2
    result=link(sources())
    assert result['status_counts']=={'linked':2}
    a,b=result['rows']
    assert a['product_quantity']=='12' and b['product_quantity']=='8'
    assert a['components'][0]['contribution']=='24'  # not 48 from repeated BOM
    assert len(a['bom_evidence'])==2
    assert a['stock_evidence'][0]['metric']=='입고/이동처리'


@pytest.mark.parametrize('cell,value,code',[('F3',3,'BOM_CONFLICT'),('F2',None,'INVALID_COMPONENT'),('F2',0,'INVALID_COMPONENT'),('F2',True,'INVALID_COMPONENT'),('F2','=2','CELL_UNAVAILABLE'),('D2','불명','USE_STATUS_REQUIRED')])
def test_invalid_bom_blocks_adoption(cell,value,code):
    w=bom_book();w.active[cell]=value;r=read_master(content(w),'2026-09','bom_master')
    assert r['status']=='needs_review' and code in {i['code'] for i in r['issues']}


def test_any_product_sharing_unsplit_source_requires_factory_quantities():
    s=sources();r=s['route_master']['records'][1]['evidence']['_normalized']['value'];r['path']='세종공업'
    result=link(s)
    assert result['status_counts']=={'factory_quantities_needed':2}
    assert all(r['product_quantity'] is None and r['components'][0]['contribution'] is None for r in result['rows'])


def test_explicit_zero_is_linked_missing_row_is_not_zero():
    s=sources();s['product_stock']['records']=[stock_row(0,'세종공업(화성)',quantity='0')]
    a,b=link(s)['rows'];assert a['product_quantity']=='0' and a['status']=='linked'
    assert b['product_quantity'] is None and b['status']=='basis_missing'


def test_semi_uses_outbound_consignment_and_flags_other_movement():
    s=sources();s['route_master']['records']=s['route_master']['records'][:1]
    r=s['route_master']['records'][0];r['evidence']['_normalized']['value']['path']='당진 경유 / 모비스 마감'
    r['evidence']['_normalized']['value']['destination']='현대 모비스'
    s['semi_stock']={'id':'semi','filename':'반제품.xlsx','records':[stock_row(0,'원자재(창고+라인)',**{'출고/적송처리':'7','출고/이동처리':'0'})]}
    row=link(s)['rows'][0];assert row['product_quantity']=='7' and row['components'][0]['destination']=='현대 모비스'
    s['semi_stock']['records'][0]['evidence']['_normalized']['value']['metrics']['출고/이동처리']='2'
    row=link(s)['rows'][0];assert row['status']=='quantity_review' and row['product_quantity'] is None


def test_glovis_receipt_bridge_and_component_exception_are_separate():
    s=sources();s['route_master']['records']=s['route_master']['records'][:1]
    r=s['route_master']['records'][0];r['part']+='_'+'CKD'
    n=r['evidence']['_normalized']['value'];n['path']='글로비스';n['destination']='99998-AA001: 현대 전주'
    for b in s['bom_master']['records'][:2]:b['part']='M99999-AA001_CKD'
    s['glovis_receipts']={'id':'glovis','filename':'실제입고.xlsx','records':[{'ordinal':0,'sheet':'입고','row_number':2,'part':'99999-AA001','quantity':'5','evidence':{'_normalized':{'value':{}}}}]}
    row=link(s)['rows'][0];assert row['product_quantity']=='5'
    assert row['components'][0]['status']=='separate_evidence_required' and row['components'][0]['contribution'] is None
    n['destination']='현대 글로비스';row=link(s)['rows'][0]
    assert row['components'][0]['contribution']=='10'
    s['glovis_receipts']['records']=[];assert link(s)['rows'][0]['product_quantity']=='0'
    del s['glovis_receipts'];assert link(s)['rows'][0]['status']=='source_missing'


def test_no_bom_suffix_fallback_and_negative_stock_needs_review():
    s=sources();s['route_master']['records'][0]['part']='M99999-AA001_CKD'
    assert link(s)['rows'][0]['status']=='bom_missing'
    s=sources();s['product_stock']['records'][0]['evidence']['_normalized']['value']['metrics']['입고/이동처리']='-2'
    assert link(s)['rows'][0]['status']=='quantity_review'


def test_preview_requires_selected_masters_and_detects_changed_source(tmp_path):
    store=Store(tmp_path);store.initialize();store.start('2026-09');imports=Imports(store)
    with pytest.raises(WorkflowError):Basis(store).preview('2026-09')
    for role, factory in [('bom_master',bom_book),('route_master',route_book)]:
        r=imports.register('2026-09',role,'2026-09',role+'.xlsx',store.get('2026-09')['revision'],content(factory()),period_confirmed=True)
        imports.select('2026-09',r['batch']['id'],store.get('2026-09')['revision'],None)
    result=Basis(store).preview('2026-09');assert result['status_counts']=={'source_missing':2}
    assert Basis(store).preview('2026-09')['input_fingerprint']==result['input_fingerprint']
    with TestClient(create_app(tmp_path),base_url='http://127.0.0.1') as client:
        response=client.get('/api/months/2026-09/basis');assert response.status_code==200
        assert response.json()['route_count']==2
    path,_=imports.original('2026-09',r['batch']['id']);path.write_bytes(b'changed')
    with pytest.raises(WorkflowError) as e:Basis(store).preview('2026-09')
    assert e.value.code=='ORIGINAL_CHANGED'


from backend.api.app import create_app
