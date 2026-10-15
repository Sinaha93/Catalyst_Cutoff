import sqlite3
import pytest
from backend.adapters.storage import Store
from backend.application.choices import Choices
from backend.application.bom_entry import BomEntry
from backend.application.masters import Masters
from backend.domain.errors import WorkflowError
from test_holds import seed
from test_closing import MONTH


def test_choices_discover_retire_restore_and_leave_business_data_unchanged(tmp_path):
    s=Store(tmp_path);seed(s);c=Choices(s);before=s.get(MONTH)
    options=c.read();assert options['categories']['customer'];assert options['categories']['path']
    assert options['categories']['warehouse']
    name=options['categories']['customer'][0]['name']
    retired=c.save('customer',name,False,0)
    assert name not in c.active('customer')
    assert name in BomEntry(s).preview(MONTH)['customers']  # Stored rows aren't rewritten.
    with pytest.raises(WorkflowError,match='변경되었습니다'):c.save('customer','새 고객',True,0)
    c.save('customer',name,True,retired['revision'])
    assert name in c.active('customer')
    assert s.get(MONTH)==before
    assert not Masters(s).overview(MONTH)['versions']


def test_added_customer_works_in_bom_and_retired_customer_cannot_be_newly_used(tmp_path):
    s=Store(tmp_path);seed(s);c=Choices(s);b=BomEntry(s)
    saved=c.save('customer','신규 고객',True,0)
    result=b.save(MONTH,s.get(MONTH)['revision'],'M99999-NEW01','99999-CC001','1','희성','신규 고객')
    original=Masters(s).get(result['version_id'])
    c.save('customer','신규 고객',False,saved['revision'])
    with pytest.raises(WorkflowError,match='선택 목록'):
        b.save(MONTH,s.get(MONTH)['revision'],'M99999-NEW02','99999-CC001','1','희성','신규 고객')
    assert Masters(s).get(result['version_id'])==original
    assert '신규 고객' not in Choices(Store(tmp_path)).active('customer')


def test_schema_five_migration_backs_up_preserves_data_and_is_repeatable(tmp_path):
    s=Store(tmp_path);seed(s);before=s.get(MONTH)
    with s.connect(write=True) as conn:
        conn.execute('DROP TABLE choice_event');conn.execute('PRAGMA user_version=5')
    s.initialize();s.initialize()
    assert s.get(MONTH)==before
    backups=list((tmp_path/'backups').glob('before-schema-6-*.sqlite'));assert len(backups)==1
    with sqlite3.connect(backups[0]) as conn:assert conn.execute('PRAGMA user_version').fetchone()[0]==5
    assert Choices(s).read()['revision']==0


@pytest.mark.parametrize('name',['','잘못\n이름','품번:마감처'])
def test_catalog_rejects_unusable_names(tmp_path,name):
    s=Store(tmp_path);s.initialize()
    with pytest.raises(WorkflowError):Choices(s).save('path',name,True,0)


def test_catalyst_destination_mapping_validated():
    from copy import deepcopy
    row={'route_id':'r','supplier':'희성','path':'경로','plant':'공장','destination':'99999-CC001:현대 울산\n99999-CC002:현대 아산','state':'설정 완료','source_role':'product_stock','warehouses':['창고'],'metric':'입고/이동처리'}
    Masters.validate_row('route_master','M99999-NEW01',deepcopy(row))
    for destination in [':현대 울산','99999-CC001:','99999-CC001:현대 울산\n99999-CC001:현대 아산']:
        with pytest.raises(WorkflowError):Masters.validate_row('route_master','M99999-NEW01',{**row,'destination':destination})
