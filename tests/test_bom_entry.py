from copy import deepcopy
import pytest
from backend.adapters.storage import Store
from backend.adapters.masters import read_master
from backend.application.bom_entry import BomEntry
from backend.application.masters import Masters, value
from backend.application.imports import Imports
from backend.application.closing import Closing
from backend.domain.errors import WorkflowError
from test_holds import seed
from test_closing import MONTH, ready
from test_masters_reset import publish


def save(s, **kw):
    return BomEntry(s).save(MONTH, s.get(MONTH)['revision'], **{
        'product': 'M99999-BB001', 'catalyst': '99999-BB001', 'usage': '1', 'supplier': '희성', **kw})


def test_append_preserves_raw_bom_and_applies_once(tmp_path):
    s=Store(tmp_path);seed(s)
    before=Imports(s).effective_sources(MONTH, ('bom_master',))['bom_master']
    revision=s.get(MONTH)['revision']
    result=save(s)
    v=Masters(s).get(result['version_id'])
    assert v['payload']['records'][:-1] == before['records']
    assert v['payload']['origin']['sha256'] == before['sha256']
    assert result['draft']['revision'] == revision+1
    assert Masters(s).overview(MONTH)['selected']['bom_master'] == v['id']
    assert read_master(Masters(s).export(v['id']), MONTH, 'bom_master')['status'] == 'ready'
    assert len(BomEntry(s).preview(MONTH)['rows']) == len(before['records'])+1
    assert isinstance(Closing(s).preview(MONTH)['rows'], list)
    with pytest.raises(WorkflowError, match='이미 등록'): save(s)
    assert s.get(MONTH)['revision'] == revision+1


def test_add_component_keeps_old_version_other_month_and_original_components(tmp_path):
    s=Store(tmp_path);seed(s);old=publish(s, 'bom_master')
    s.start('2026-10')
    original=deepcopy(Masters(s).get(old)['payload']['records'])
    part=original[0]['part']
    result=save(s, product=part)
    updated=Masters(s).get(result['version_id'])['payload']['records']
    for before, after in zip(original, updated):
        if before['part']==part:
            assert value(after)['components'][:-1] == value(before)['components']
            assert value(after)['components'][-1]['part']=='99999-BB001'
        else: assert before == after
    assert Masters(s).get(old)['payload']['records']==original
    assert Masters(s).overview('2026-10')['selected']['bom_master']==old


@pytest.mark.parametrize('usage', ['0','-1','NaN','Infinity','abc','0.0000001'])
def test_invalid_usage_does_not_mutate(tmp_path, usage):
    s=Store(tmp_path);seed(s);revision=s.get(MONTH)['revision']
    with pytest.raises(WorkflowError): save(s, usage=usage)
    assert s.get(MONTH)['revision']==revision
    assert not Masters(s).overview(MONTH)['versions']


def test_stale_revision_and_finalized_are_rejected(tmp_path):
    s=Store(tmp_path);c=ready(s);revision=s.get(MONTH)['revision']
    v=c.preview(MONTH);c.finalize(MONTH,v['revision'],v['fingerprint'],'bom-entry-final')
    with pytest.raises(WorkflowError, match='확정본'): save(s)
    s2=Store(tmp_path/'other');seed(s2);old=s2.get(MONTH)['revision'];save(s2)
    with pytest.raises(WorkflowError, match='월 작업이 변경'):
        BomEntry(s2).save(MONTH,old,'M99999-BB002','99999-BB002','1','희성')


def test_empty_master_can_start_with_one_row(tmp_path):
    s=Store(tmp_path);s.initialize();s.start(MONTH)
    result=save(s)
    assert len(Masters(s).get(result['version_id'])['payload']['records'])==1


def test_customer_selection_rejects_typo_and_keeps_existing_names(tmp_path):
    s=Store(tmp_path);seed(s);entry=BomEntry(s)
    before=entry.preview(MONTH);customer=before['customers'][0]
    with pytest.raises(WorkflowError,match='고객사 목록'):
        save(s,customer=customer+'오타')
    assert s.get(MONTH)['revision']==before['revision']
    result=save(s,customer=customer,supplier='희성촉매(주)')
    added=Masters(s).get(result['version_id'])['payload']['records'][-1]
    assert value(added)['customer']==customer and value(added)['supplier']=='희성'


def test_supplier_selection_and_exact_legal_name_aliases(tmp_path):
    from backend.application.partner_names import selected_supplier
    assert selected_supplier('희성촉매(주)')=='희성'
    assert selected_supplier('한국유미코아촉매')=='유미코아'
    s=Store(tmp_path);seed(s);revision=s.get(MONTH)['revision']
    with pytest.raises(WorkflowError,match='촉매사는 목록'):
        save(s,supplier='희셩')
    m=Masters(s);e=m.editor(MONTH,'route_master')
    e['rows'][0]['supplier']='유미코아아'
    with pytest.raises(WorkflowError,match='촉매사는 목록'):
        m.proposal(MONTH,'route_master',MONTH,None,'오타 검증',None,rows=e['rows'])
    assert s.get(MONTH)['revision']==revision


def test_existing_bom_legal_supplier_name_accepts_selected_supplier(tmp_path):
    from test_basis import bom_book, content
    s=Store(tmp_path);seed(s);w=bom_book()
    for row in w.active.iter_rows(min_row=2):row[2].value='희성촉매(주)'
    imp=Imports(s);previous=next(b['id'] for b in imp.list(MONTH) if b['role']=='bom_master' and b['selected'])
    registered=imp.register(MONTH,'bom_master',MONTH,'legal-name.xlsx',s.get(MONTH)['revision'],content(w),period_confirmed=True)
    imp.select(MONTH,registered['batch']['id'],s.get(MONTH)['revision'],previous)
    result=save(s,product='M99999-AA001')
    matching=[r for r in Masters(s).get(result['version_id'])['payload']['records'] if r['part']=='M99999-AA001']
    assert all(value(r)['supplier']=='희성촉매(주)' and len(value(r)['components'])==2 for r in matching)
