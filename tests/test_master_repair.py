from copy import deepcopy
import pytest
from backend.adapters.storage import Store
from backend.application.masters import Masters
from backend.application.imports import Imports
from backend.domain.errors import WorkflowError
from test_holds import seed
from test_closing import MONTH, PART
from test_masters_reset import publish


def test_editor_uses_active_raw_routes_and_exact_bom_products(tmp_path):
    s=Store(tmp_path);seed(s);m=Masters(s)
    before=s.get(MONTH)['revision']
    e=m.editor(MONTH,'route_master',PART)
    assert e['products'] and all(p!=PART for p in e['products'])
    assert e['rows'][0]['source_role']=='product_stock'
    assert e['rows'][0]['warehouses']
    assert m.editor(MONTH,'route_master','UNKNOWN-00')['products']==[]
    assert m.editor(MONTH,'route_master','H28950-TEST','product')['products']==['H28950-TEST']
    assert s.get(MONTH)['revision']==before


def test_save_apply_preserves_other_rows_and_other_month(tmp_path):
    s=Store(tmp_path);seed(s);m=Masters(s);old=publish(s)
    s.start('2026-10');e=m.editor(MONTH,'route_master',PART)
    rows=deepcopy(e['rows']);rows[0]['plant']='울산5공장'
    args=dict(role='route_master',effective_from=MONTH,effective_to=None,reason='경로 수정 검증',expected_head=e['expected_head'],rows=rows)
    p=m.proposal(MONTH,**args)
    result=m.publish(MONTH,e['revision'],p['fingerprint'],apply=True,**args)
    assert result['draft']['revision']==e['revision']+1
    assert m.overview(MONTH)['selected']['route_master']==result['version_id']
    assert m.overview('2026-10')['selected']['route_master']==old
    assert m.editor(MONTH,'route_master',PART)['rows'][1:]==e['rows'][1:]
    assert m.editor(MONTH,'route_master',PART)['rows'][0]['plant']=='울산5공장'
    with pytest.raises(WorkflowError):m.publish(MONTH,e['revision'],p['fingerprint'],apply=True,**args)


def test_out_of_period_apply_rolls_back_version(tmp_path):
    s=Store(tmp_path);seed(s);m=Masters(s);e=m.editor(MONTH,'route_master',PART)
    args=dict(role='route_master',effective_from='2026-10',effective_to=None,reason='기간 충돌',expected_head=e['expected_head'],rows=e['rows'])
    p=m.proposal(MONTH,**args)
    with pytest.raises(WorkflowError,match='적용할 수 없는'):m.publish(MONTH,e['revision'],p['fingerprint'],apply=True,**args)
    assert not m.overview(MONTH)['versions']
    assert s.get(MONTH)['revision']==e['revision']


def test_price_editor_retains_conflicts_and_deduplicates_equal_prices(tmp_path):
    from openpyxl import Workbook
    from test_pricing import content
    s=Store(tmp_path);seed(s);w=Workbook();w.active.append(['품번','단가'])
    for part,price in [(PART,10),(PART,10),(PART,11),('99999-BB001',20)]:w.active.append([part,price])
    imp=Imports(s);r=imp.register(MONTH,'price_master',MONTH,'price.xlsx',s.get(MONTH)['revision'],content(w),period_confirmed=True)
    imp.select(MONTH,r['batch']['id'],s.get(MONTH)['revision'],None)
    rows=Masters(s).editor(MONTH,'price_master',PART)['rows']
    assert len(rows)==3 and {r['price'] for r in rows if r['part']==PART}=={'10','11'}
