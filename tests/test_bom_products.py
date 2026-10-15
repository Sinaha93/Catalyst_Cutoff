import pytest
from backend.adapters.storage import Store
from backend.application.bom_entry import BomEntry
from backend.application.masters import Masters, value
from backend.domain.errors import WorkflowError
from test_holds import seed
from test_closing import MONTH


def test_multi_products_customers_saved_as_rows_in_one_version(tmp_path):
    s=Store(tmp_path);seed(s);service=BomEntry(s);before=service.preview(MONTH)
    customers=before['customers'];assert len(customers)>=2
    products=[{'product':'M99999-NEW01','usage':'1','customers':customers[:2]},
              {'product':'H99999-NEW02','usage':'2','customers':[customers[0]]}]
    result=service.save_many(MONTH,before['revision'],'99999-CC001','희성',products)
    rows=Masters(s).get(result['version_id'])['payload']['records']
    assert len(rows)==len(before['rows'])+3
    assert result['draft']['revision']==before['revision']+1
    assert len(Masters(s).overview(MONTH)['versions'])==1
    added=rows[-3:]
    assert [r['part'] for r in added]==['M99999-NEW01','M99999-NEW01','H99999-NEW02']
    assert [value(r)['components'][0]['usage'] for r in added]==['1','1','2']
    assert [value(r)['customer'] for r in added]==[customers[0],customers[1],customers[0]]


@pytest.mark.parametrize('bad',[
    {'product':'H99999-NEW02','usage':'0','customers':[]},
    {'product':'M99999-NEW01','usage':'1','customers':[]},
    {'product':'H99999-NEW02','usage':'1','customers':['고객 A','고객 A']},
    {'product':'H99999-NEW02','usage':'1','customers':['고객오타']},
])
def test_batch_invalid_second_product_writes_nothing(tmp_path,bad):
    s=Store(tmp_path);seed(s);before=s.get(MONTH)['revision']
    with pytest.raises(WorkflowError):
        BomEntry(s).save_many(MONTH,before,'99999-CC001','희성',[
            {'product':'M99999-NEW01','usage':'1','customers':[]},bad])
    assert s.get(MONTH)['revision']==before
    assert not Masters(s).overview(MONTH)['versions']


def test_existing_composition_is_preserved_for_new_customer(tmp_path):
    s=Store(tmp_path);seed(s);b=BomEntry(s);customers=b.preview(MONTH)['customers']
    def add(catalyst,usage,cs):
        return b.save_many(MONTH,s.get(MONTH)['revision'],catalyst,'희성',[
            {'product':'M99999-NEW01','usage':usage,'customers':cs}])
    add('99999-CC001','1',[customers[0]])
    add('99999-CC002','2',[])
    result=add('99999-CC001','1',[customers[1]])
    rows=[r for r in Masters(s).get(result['version_id'])['payload']['records'] if r['part']=='M99999-NEW01']
    assert len(rows)==2
    assert value(rows[0])['components']==value(rows[1])['components']
    assert len(value(rows[1])['components'])==2
    with pytest.raises(WorkflowError,match='소요량은 1'):add('99999-CC001','3',[])
