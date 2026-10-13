from copy import deepcopy
from io import BytesIO
import openpyxl
import pytest
from fastapi.testclient import TestClient

from backend.adapters.ledger import read_ledger
from backend.adapters.storage import Store
from backend.application.imports import Imports
from backend.application.reconciliation import Reconciliation, reconcile
from backend.api.app import create_app
from backend.domain.errors import WorkflowError


def record(part,quantity=None,**normalized):
    return {'part':part,'quantity':quantity,'ordinal':0,'sheet':'원본','row_number':4,'evidence':{'_normalized':{'value':normalized}}}


def source(role,records):return {'id':role,'filename':role+'.xlsx','records':records}


def sources(prior='3',incoming='7',ledger_prior='3',erp='7',held='4'):
    p='99999-AA001'
    return {'heesung_shipments':source('hs',[record(p,incoming)]),
            'heesung_carryover':source('carry',[record(p,prior)]),
            'erp_receipts':source('erp',[record(p,erp,included=True)]),
            'comparison_report':source('report',[record(p,held,prior=ledger_prior,held=held,destination='현대 울산',reason='보류',partial_incoming='999')])}


def test_independent_composition_match_proposes_pool_but_never_historical_hold():
    row=reconcile(sources())['rows'][0]
    assert row['status']=='matched' and row['supplier_available']==row['ledger_available']=='10'
    assert row['erp_incoming']=='7'  # not partial report purchases 999
    assert row['historical_held']=='4' and row['suggested_pool']['미마감보류'] is None
    assert row['suggested_pool']=={'전월이월':'3','당월입고':'7','조정':'0','미마감보류':None}


def test_equal_total_with_different_period_composition_is_not_automatic_match():
    row=reconcile(sources(prior='0',incoming='263',ledger_prior='95',erp='168'))['rows'][0]
    assert row['status']=='composition_difference' and row['total_difference']=='0'
    assert row['prior_difference']=='-95' and row['incoming_difference']=='95' and row['suggested_pool'] is None


def test_difference_kept_not_adjusted_to_erp_or_report():
    row=reconcile(sources(prior='0',incoming='595',ledger_prior='0',erp='593'))['rows'][0]
    assert row['status']=='total_difference' and row['total_difference']=='2'
    assert row['supplier_available']=='595' and row['ledger_available']=='593' and row['suggested_pool'] is None


def test_signed_supplier_corrections_are_preserved():
    row=reconcile(sources(prior='4',incoming='-4',ledger_prior='0',erp='0'))['rows'][0]
    assert row['supplier_available']=='0' and row['supplier_incoming']=='-4' and row['status']=='composition_difference'


def test_absent_source_is_not_zero_but_adopted_complete_source_without_row_is():
    s=sources();del s['heesung_carryover'];row=reconcile(s)['rows'][0]
    assert row['supplier_prior'] is None and row['status']=='source_missing'
    s['heesung_carryover']=source('carry',[]);row=reconcile(s)['rows'][0]
    assert row['supplier_prior']=='0' and 'heesung_carryover' in row['absent_from'] and row['status']=='total_difference'


def test_supplier_collision_and_direct_supply_remain_unresolved():
    s=sources();s['umicore_statement']=source('umi',[record('99999-AA001',metrics={'전월 적송재고':'3','납품 수량':'7'})])
    assert reconcile(s)['rows'][0]['status']=='supplier_conflict'
    s=sources();del s['heesung_shipments'];del s['heesung_carryover']
    assert reconcile(s)['rows'][0]['status']=='supplier_missing'


def test_umicore_only_uses_summary_delivery_not_reported_closing():
    s=sources();del s['heesung_shipments'];del s['heesung_carryover']
    s['umicore_statement']=source('umi',[record('99999-AA001','900',metrics={'전월 적송재고':'3','납품 수량':'7','원문 마감 표기':'900'})])
    r=reconcile(s)['rows'][0];assert r['supplier']=='유미코아' and r['supplier_available']=='10'


def test_excluded_converters_not_added_and_multiple_ledger_destinations_sum_once():
    s=sources();s['erp_receipts']['records'].append(record('289E0-4A720','833',included=False))
    extra=deepcopy(s['comparison_report']['records'][0]);extra['ordinal']=1;extra['evidence']['_normalized']['value'].update(prior='2',held='1',destination='기아 화성');s['comparison_report']['records'].append(extra)
    r=reconcile(s);assert len(r['rows'])==1 and r['rows'][0]['ledger_prior']=='5' and r['rows'][0]['historical_held']=='5'


def book():
    w=openpyxl.Workbook();s=w.active;s.title='미정산품목(26년9월)'
    s.append([None,'9월 이월 및 정산품목'])
    s.append([None,'NO','구분','차종','품 번','단가구분','매입단가','미정산수량',None,None,None,'금액','비고',None])
    s.append([None,None,None,None,None,None,None,'전월','8월 매입','8월 마감','미마감 계'])
    s.append([None,1,'현대 울산',None,'99999-AA001','정',1,3,7,6,4,4,'개발 이벤트'])
    s.append([None,None,'소 계',None,None,None,None,3,7,6,4])
    s.append([None,'합 계',None,None,None,None,None,3,7,6,4])
    return w


def content(w):
    b=BytesIO();w.save(b);w.close();return b.getvalue()


def test_report_preserves_original_header_and_partial_values_separately():
    r=read_ledger(content(book()),'2026-09');assert r['status']=='ready' and len(r['records'])==1
    n=r['records'][0]['evidence']['_normalized']['value'];assert n['prior']=='3' and n['partial_incoming']=='7' and n['held']=='4'


@pytest.mark.parametrize('cell,value',[('H4',None),('H4',True),('H4','=3'),('K4',5),('K6',5),('H4',-3)])
def test_report_invalid_quantities_and_total_mismatch_block(cell,value):
    w=book();w.active[cell]=value
    assert read_ledger(content(w),'2026-09')['status']=='needs_review'


def test_report_duplicate_part_destination_and_wrong_period_block():
    w=book();w.active.insert_rows(5);w.active.append([])
    for i,c in enumerate(w.active[4],1):w.active.cell(5,i,c.value)
    assert read_ledger(content(w),'2026-09')['status']=='needs_review'
    with pytest.raises(WorkflowError):read_ledger(content(book()),'2026-10')


def test_report_blank_partial_purchase_is_not_imputed_as_whole_month_zero():
    w=book();w.active['I4']=None
    r=read_ledger(content(w),'2026-09');assert r['status']=='ready'
    assert r['records'][0]['evidence']['_normalized']['value']['partial_incoming'] is None


def test_adopted_report_api_and_source_integrity(tmp_path):
    store=Store(tmp_path);store.initialize();store.start('2026-09');imports=Imports(store)
    r=imports.register('2026-09','comparison_report','2026-09','비교.xlsx',1,content(book()),period_confirmed=True)
    imports.select('2026-09',r['batch']['id'],r['draft']['revision'],None)
    with TestClient(create_app(tmp_path),base_url='http://127.0.0.1') as client:
        response=client.get('/api/months/2026-09/reconciliation');assert response.status_code==200
        row=response.json()['rows'][0];assert row['status']=='supplier_missing' and row['erp_incoming'] is None
        assert row['evidence']['comparison_report'][0]['filename']=='비교.xlsx'
    p,_=imports.original('2026-09',r['batch']['id']);p.write_bytes(b'changed')
    with pytest.raises(WorkflowError) as e:Reconciliation(store).preview('2026-09')
    assert e.value.code=='ORIGINAL_CHANGED'
