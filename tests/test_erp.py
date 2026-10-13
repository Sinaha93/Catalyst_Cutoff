from io import BytesIO

import openpyxl
import pytest
from fastapi.testclient import TestClient

from backend.adapters.erp import read_erp
from backend.adapters.storage import Store
from backend.api.app import create_app
from backend.application.imports import Imports
from backend.domain.errors import WorkflowError


def receipt_book():
    book = openpyxl.Workbook(); s = book.active
    s.append(['기간별구매거래처입고현황'])
    s.append(['품목자산분류', '품명', '품번', '합계', '가상 거래처 A', '가상 거래처 B'])
    s.append(['품목자산분류', '품명', '품번', '수량계', '수량', '수량'])
    s.append(['TOTAL', '', '', 19, 14, 5])
    s.append(['4.촉매,귀금속', 'CATALYST', 'R60099999-AA001', 8, 10, -2])
    s.append(['4.촉매,귀금속', 'CATALYST', 'R60099999-AA002', 0, 0, 0])
    s.append(['4.촉매,귀금속', 'CONVERTER', 'R600289E0-4A120', 4, 4, 0])
    s.append(['4.촉매,귀금속', 'CONVERTER', 'R600289E0-4A720', 7, 0, 7])
    return book


def stock_book(semi=False):
    book = openpyxl.Workbook(); s = book.active
    s.append(['창고별 수불집계조회'])
    s.append(['품목자산분류', '창고', '품명', '품번', '이월수량', '입고수량', '출고수량', '재고수량', '입고', '출고', '출고'])
    s.append(['품목자산분류', '창고', '품명', '품번', '이월수량', '입고수량', '출고수량', '재고수량', '이동처리', '이동처리', '적송처리'])
    s.append(['TOTAL', '', '', '', 5, 12, 14, 3, 12, 10, 4])
    s.append(['3.반제품' if semi else '1.제품', '가상 창고', '가상 제품', 'H289G0-AA001' if semi else 'M99999-AA001', 5, 12, 14, 3, 12, 10, 4])
    return book


def content(book):
    b = BytesIO(); book.save(b); book.close(); return b.getvalue()


def test_erp_receipt_excludes_only_confirmed_converters_and_preserves_cells():
    r = read_erp(content(receipt_book()), '2026-09', 'erp_receipts')
    assert r['status'] == 'ready'
    assert (r['summary']['raw_quantity_total'], r['summary']['quantity_total'], r['summary']['excluded_quantity_total']) == ('19', '8', '11')
    assert r['summary']['aggregates'] == {'99999-AA001': '8', '99999-AA002': '0'}
    assert r['records'][0]['evidence']['F5']['value'] == -2
    assert r['records'][1]['quantity'] == '0'
    assert r['records'][3]['evidence']['_normalized']['value']['included'] is False
    assert r['summary']['controls'][0]['evidence']['D4']['value'] == 19


@pytest.mark.parametrize('cell,value,code', [('D5', None, 'QUANTITY_UNAVAILABLE'), ('D5', '=10-2', 'QUANTITY_UNAVAILABLE'), ('D5', '#REF!', 'QUANTITY_UNAVAILABLE'), ('D5', 9, 'ROW_TOTAL_MISMATCH'), ('D4', 99, 'CONTROL_TOTAL_MISMATCH'), ('B5', 'UNKNOWN', 'ITEM_SCOPE_REVIEW'), ('C6', 'R60099999-AA001', 'DUPLICATE_ROW'), ('C5', 'broken', 'INVALID_PART')])
def test_bad_receipt_evidence_blocks_adoption(cell, value, code):
    book = receipt_book(); book.active[cell] = value
    r = read_erp(content(book), '2026-09', 'erp_receipts')
    assert r['status'] == 'needs_review'
    assert code in {i['code'] for i in r['issues']}
    assert len(r['records']) == 4
    if code == 'QUANTITY_UNAVAILABLE': assert r['records'][0]['quantity'] is None


def test_shifted_headers_and_reordered_customer_columns():
    book = receipt_book(); s = book.active
    s.insert_rows(1, 3)
    for row in s:
        row[4].value, row[5].value = row[5].value, row[4].value
    r = read_erp(content(book), '2026-09', 'erp_receipts')
    assert r['status'] == 'ready'
    assert r['records'][0]['row_number'] == 8
    assert r['records'][0]['evidence']['_normalized']['value']['by_customer'] == {'가상 거래처 B': '-2', '가상 거래처 A': '10'}


@pytest.mark.parametrize('semi', [False, True])
def test_stock_directions_and_carryover_are_independent(semi):
    r = read_erp(content(stock_book(semi)), '2026-09', 'semi_stock' if semi else 'product_stock')
    assert r['status'] == 'ready'
    assert 'quantity_total' not in r['summary']
    assert r['records'][0]['quantity'] is None
    n = r['records'][0]['evidence']['_normalized']['value']
    assert n['metrics']['입고/이동처리'] == '12'
    assert n['metrics']['출고/이동처리'] == '10'
    assert n['metrics']['출고/적송처리'] == '4'
    assert n['metrics']['이월수량'] == '5'
    assert n['semi_catalyst_candidate'] == semi


def test_stock_balance_bad_scope_and_duplicate_processing_columns():
    book = stock_book(); book.active['H5'] = 4
    assert 'STOCK_BALANCE_MISMATCH' in {i['code'] for i in read_erp(content(book), '2026-09', 'product_stock')['issues']}
    assert read_erp(content(stock_book()), '2026-09', 'semi_stock')['status'] == 'needs_review'
    book = stock_book(); book.active['K3'] = '이동처리'
    assert read_erp(content(book), '2026-09', 'product_stock')['status'] == 'needs_review'


def test_period_confirmation_registration_dedup_selection_and_reread(tmp_path):
    store = Store(tmp_path); store.initialize(); store.start('2026-09'); svc = Imports(store)
    b = content(receipt_book())
    with pytest.raises(WorkflowError) as e:
        svc.register('2026-09', 'erp_receipts', '2026-09', '다운로드_20261008.xlsx', 1, b)
    assert e.value.code == 'PERIOD_CONFIRM_REQUIRED'
    r = svc.register('2026-09', 'erp_receipts', '2026-09', '다운로드_20261008.xlsx', 1, b, period_confirmed=True)
    assert r['batch']['source_period'] == '2026-09'
    assert r['batch']['result']['summary']['period_confirmed'] is True
    assert svc.register('2026-09', 'erp_receipts', '2026-09', '다른이름.xlsx', 2, b, period_confirmed=True)['duplicate']
    svc.select('2026-09', r['batch']['id'], 2, None)
    reread = svc.reread('2026-09', r['batch']['id'], 3)
    assert reread['batch']['status'] == 'ready' and reread['batch']['selected'] == 0
    assert svc.detail('2026-09', r['batch']['id'])['selected'] == 1


def test_erp_api_requires_period_and_keeps_roles_separate(tmp_path):
    store = Store(tmp_path); store.initialize(); store.start('2026-09')
    with TestClient(create_app(tmp_path), base_url='http://127.0.0.1') as client:
        token = client.get('/api/session').json()['token']
        headers = {'X-Session-Token': token, 'Origin': 'http://127.0.0.1'}
        params = {'role': 'product_stock', 'source_period': '2026-09', 'filename': '수불.xlsx', 'expected_revision': 1}
        b = content(stock_book())
        response = client.post('/api/months/2026-09/sources', params=params, content=b, headers=headers)
        assert response.status_code == 400
        params['period_confirmed'] = 'true'
        response = client.post('/api/months/2026-09/sources', params=params, content=b, headers=headers)
        assert response.status_code == 200, response.text
        batch = response.json()['batch']
        assert batch['role'] == 'product_stock' and batch['status'] == 'ready'
        response = client.get(f"/api/months/2026-09/sources/{batch['id']}")
        assert response.json()['records'][0]['evidence']['_normalized']['value']['metrics']['입고/이동처리'] == '12'
