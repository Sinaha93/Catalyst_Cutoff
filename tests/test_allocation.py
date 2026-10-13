from copy import deepcopy
from decimal import Decimal
from io import BytesIO

import openpyxl
import pytest
from fastapi.testclient import TestClient

from backend.adapters.allocation import HEADERS, read_allocation
from backend.adapters.storage import Store
from backend.application.allocation import Allocation, calculate, rounded_allocation
from backend.application.basis import Basis, link
from backend.application.imports import Imports
from backend.api.app import create_app
from backend.domain.errors import WorkflowError
from test_basis import sources, content, bom_book, route_book
from test_erp import stock_book


def pool(part='99998-AA001', previous='3', incoming='98', adjustment='0', held='0'):
    return {'kind':'촉매총량','key':part,'quantities':{'전월이월':previous,'당월입고':incoming,'조정':adjustment,'미마감보류':held},'reason':'대조 완료','basis':'원본 2행'}


def split(route, quantity):
    return {'kind':'공장수량','key':route,'quantities':{'공장별납품수량':quantity},'reason':'납품 구분','basis':'거래 내역 3행'}


def test_pool_is_allocated_once_not_capped_by_product_quantity():
    basis=link(sources());r=calculate(basis,[pool()])['rows'][0]
    assert r['status']=='ready' and r['available']=='101' and r['balance']=='0'
    assert {d['destination']:d['quantity'] for d in r['destinations']}=={'기아 화성':'40','현대 울산':'61'}
    assert basis['rows'][0]['components'][0]['contribution']=='24'  # no input mutation


def test_same_catalyst_across_products_combines_weights_before_allocation():
    b=link(sources());extra=deepcopy(b['rows'][1]);extra['product']='MOTHER-PART';extra['route_id']='R3';extra['components'][0]['contribution']='60';b['rows'].append(extra)
    r=calculate(b,[pool(previous='0',incoming='100')])['rows'][0]
    assert r['weights']=={'현대 울산':'24','기아 화성':'76'}
    assert sorted(d['quantity'] for d in r['destinations'])==['24','76']


def test_missing_basis_does_not_silently_redistribute_other_plants():
    s=sources();s['product_stock']['records']=s['product_stock']['records'][:1]
    r=calculate(link(s),[pool()])['rows'][0]
    assert r['status']=='basis_incomplete' and r['closing_total'] is None and not r['destinations']


def test_pool_missing_displays_ratios_without_claiming_zero_closing():
    r=calculate(link(sources()),[])['rows'][0]
    assert r['status']=='pool_required' and r['closing_total'] is None
    assert r['ratios']=={'현대 울산':'0.6','기아 화성':'0.4'}


def shared_basis():
    s=sources();s['route_master']['records'][1]['evidence']['_normalized']['value']['path']='세종공업'
    return link(s)


def test_generic_factory_split_conserves_single_source_total():
    r=calculate(shared_basis(),[split('R1','7'),split('R2','5'),pool(previous='0',incoming='120')])['rows'][0]
    assert r['status']=='ready' and r['weights']=={'현대 울산':'14','기아 화성':'10'}
    assert {d['destination']:d['quantity'] for d in r['destinations']}=={'기아 화성':'50','현대 울산':'70'}


@pytest.mark.parametrize('inputs,code',[
    ([split('R1','7')],'SPLIT_INCOMPLETE'),
    ([split('R1','12'),split('R2','12')],'SPLIT_TOTAL_MISMATCH'),
    ([split('R9','12')],'SPLIT_ROUTE_CHANGED'),
])
def test_split_rejects_partial_duplicate_and_stale_routes(inputs,code):
    with pytest.raises(WorkflowError) as e:calculate(shared_basis(),inputs)
    assert e.value.code==code


def test_glovis_actual_receipt_excluded_from_rounding_and_remainder():
    b=link(sources());g=deepcopy(b['rows'][0]);g.update(route_id='G',basis_kind='actual_receipt');g['components'][0].update(destination='현대 글로비스',contribution='7');b['rows'].append(g)
    r=calculate(b,[pool(previous='0',incoming='100',held='10')])['rows'][0]
    assert r['status']=='ready' and r['closing_total']=='90' and r['balance']=='0'
    quantities={d['destination']:d['quantity'] for d in r['destinations']}
    assert quantities=={'기아 화성':'33','현대 울산':'50','현대 글로비스':'7'}
    b['rows']=[g]
    assert calculate(b,[pool(previous='0',incoming='100',held='10')])['rows'][0]['status']=='hold_required'
    assert calculate(b,[pool(previous='0',incoming='5')])['rows'][0]['status']=='pool_conflict'
    assert calculate(b,[pool(previous='0',incoming='100',held='93')])['rows'][0]['status']=='ready'


def test_umicore_not_automatically_subject_to_heesung_ratio():
    b=link(sources());b['rows'][0]['supplier']='유미코아'
    assert calculate(b,[pool()])['rows'][0]['status']=='supplier_rule_pending'


def test_rounding_half_up_preserves_total_and_is_order_independent():
    weights={'C':Decimal(1),'B':Decimal(1),'A':Decimal(1),'Z':Decimal(0)}
    for total in range(30):
        r=rounded_allocation(Decimal(total),weights)
        assert r==rounded_allocation(Decimal(total),dict(reversed(list(weights.items()))))
        assert sum(Decimal(x['quantity']) for x in r.values())==total
        assert all(Decimal(x['quantity'])>=0 for x in r.values()) and r['Z']['quantity']=='0'
    r=rounded_allocation(Decimal(1),{'A':Decimal(1),'B':Decimal(1)})
    assert r['A']['rounded']=='1' and r['B']['rounded']=='1' and r['A']['correction']=='-1'


def test_single_destination_needs_no_ratio_but_zero_multiple_destinations_blocks():
    assert rounded_allocation(Decimal(3),{'A':Decimal(0)})['A']['quantity']=='3'
    with pytest.raises(WorkflowError):rounded_allocation(Decimal(3),{'A':Decimal(0),'B':Decimal(0)})


def input_book(fingerprint='a'*64):
    w=openpyxl.Workbook();s=w.active;s.title='배분입력';s.append(HEADERS)
    s.append(['2026-09',fingerprint,'촉매총량',None,'99998-AA001',3,98,0,0,None,'대조 완료','이월 원본!2행 / 입고!3행'])
    return w


@pytest.mark.parametrize('cell,value',[('F2',None),('F2',True),('F2','=3'),('G2',-1),('I2',102),('J2',1),('K2',None),('B2','wrong'),('A2','2026-10')])
def test_input_parser_rejects_unverified_quantities(cell,value):
    w=input_book();w.active[cell]=value
    assert read_allocation(content(w),'2026-09')['status']=='needs_review'


def test_blank_template_rows_are_not_zero_and_duplicates_block():
    w=input_book();w.active.append(['2026-09','a'*64,'촉매총량',None,'99998-AA002'])
    r=read_allocation(content(w),'2026-09');assert r['status']=='ready' and len(r['records'])==1
    w=input_book();w.active.append([c.value for c in w.active[2]])
    assert read_allocation(content(w),'2026-09')['status']=='needs_review'


def test_api_template_adoption_and_stale_fingerprint_guard(tmp_path):
    store=Store(tmp_path);store.initialize();store.start('2026-09');imports=Imports(store)
    for role,factory in [('bom_master',bom_book),('route_master',route_book)]:
        r=imports.register('2026-09',role,'2026-09',role+'.xlsx',store.get('2026-09')['revision'],content(factory()),period_confirmed=True)
        imports.select('2026-09',r['batch']['id'],store.get('2026-09')['revision'],None)
    basis=Basis(store).preview('2026-09')
    with TestClient(create_app(tmp_path),base_url='http://127.0.0.1') as client:
        template=client.get('/api/months/2026-09/allocation-template');assert template.status_code==200
        assert read_allocation(template.content,'2026-09')['status']=='needs_review'
        r=imports.register('2026-09','allocation_inputs','2026-09','수량.xlsx',store.get('2026-09')['revision'],content(input_book(basis['input_fingerprint'])),period_confirmed=True)
        imports.select('2026-09',r['batch']['id'],store.get('2026-09')['revision'],None)
        preview=client.get('/api/months/2026-09/allocation');assert preview.status_code==200
        assert preview.json()['rows'][0]['status']=='basis_incomplete'
        previous=next(b['id'] for b in imports.list('2026-09') if b['role']=='route_master' and b['selected'])
        w=route_book();w.active['H2']='기준 변경'
        r=imports.register('2026-09','route_master','2026-09','경로수정.xlsx',store.get('2026-09')['revision'],content(w),period_confirmed=True)
        imports.select('2026-09',r['batch']['id'],store.get('2026-09')['revision'],previous)
        response=client.get('/api/months/2026-09/allocation')
        assert response.status_code==409 and response.json()['code']=='ALLOCATION_BASIS_CHANGED'


def test_saved_input_survives_reopen_and_full_api_calculation(tmp_path):
    store=Store(tmp_path);store.initialize();store.start('2026-09');imports=Imports(store)
    stock=stock_book();stock.active['B5']='세종공업(화성)'
    route=route_book();route.active['D3']='세종공업'
    for role,w in [('bom_master',bom_book()),('route_master',route),('product_stock',stock)]:
        r=imports.register('2026-09',role,'2026-09',role+'.xlsx',store.get('2026-09')['revision'],content(w),period_confirmed=True)
        imports.select('2026-09',r['batch']['id'],store.get('2026-09')['revision'],None)
    fingerprint=Basis(store).preview('2026-09')['input_fingerprint']
    w=input_book(fingerprint)
    for rid,qty in [('R1',7),('R2',5)]:w.active.append(['2026-09',fingerprint,'공장수량',rid,None,None,None,None,None,qty,'납품 구분','전산 거래내역'])
    r=imports.register('2026-09','allocation_inputs','2026-09','확인수량.xlsx',store.get('2026-09')['revision'],content(w),period_confirmed=True)
    imports.select('2026-09',r['batch']['id'],store.get('2026-09')['revision'],None)
    with TestClient(create_app(tmp_path),base_url='http://127.0.0.1') as client:
        row=client.get('/api/months/2026-09/allocation').json()['rows'][0]
        assert row['status']=='ready' and row['closing_total']=='101' and row['balance']=='0'
        assert {r['destination']:r['quantity'] for r in row['destinations']}=={'기아 화성':'42','현대 울산':'59'}
        assert row['pool']['evidence']['filename']=='확인수량.xlsx'
    assert Allocation(Store(tmp_path)).preview('2026-09')['rows'][0]==row
