"""Append a verified product/catalyst link to the month's active BOM atomically."""
from copy import deepcopy
from decimal import Decimal, InvalidOperation
import json
from uuid import uuid4

from backend.adapters.heesung import PART
from backend.adapters.masters import PRODUCT
from backend.adapters.storage import now
from backend.application.imports import Imports
from backend.application.masters import Masters, value
from backend.domain.errors import WorkflowError
from backend.application.partner_names import selected_supplier, supplier_name, customer_options
from backend.application.choices import Choices


class BomEntry:
    def __init__(self, store): self.store = store

    def current(self, month):
        before = self.store.get(month)
        source = Imports(self.store).effective_sources(month, ('bom_master',)).get('bom_master')
        return before, source

    def preview(self, month):
        draft, source = self.current(month)
        return {'revision': draft['revision'], 'customers': customer_options((source or {}).get('records', [])), 'rows': [
            {'part': r['part'], **value(r)} for r in (source or {}).get('records', [])]}

    def save(self, month, revision, product, catalyst, usage, supplier, customer=''):
        return self.save_many(month, revision, catalyst, supplier,
                              [{'product': product, 'usage': usage, 'customers': [customer] if customer else []}])

    @staticmethod
    def add_product(records, entry, catalyst, supplier, allowed_customers):
        product = entry['product'].strip().upper()
        if not PRODUCT.fullmatch(product):
            raise WorkflowError('BOM_PART', '제품 품번을 확인해 주세요. M/H와 접미사는 구분됩니다.')
        try: quantity = Decimal(entry['usage'])
        except InvalidOperation: quantity = Decimal('NaN')
        if not quantity.is_finite() or quantity <= 0 or quantity > 10000 or quantity.as_tuple().exponent < -6:
            raise WorkflowError('BOM_USAGE', f'{product}: 제품 1개당 촉매 소요량을 0보다 큰 수로 입력해 주세요. 소수점 6자리까지 가능합니다.')
        customers = [c.strip() for c in entry.get('customers', [])]
        if len(customers) != len(set(customers)):
            raise WorkflowError('BOM_CUSTOMER_DUPLICATE', f'{product}: 같은 고객사를 중복 선택했습니다.')
        if any(c not in allowed_customers for c in customers):
            raise WorkflowError('BOM_CUSTOMER', '사용 중인 고객사 목록에서 선택해 주세요. 새 고객사는 선택 목록 관리에서 추가할 수 있습니다.')
        matched = [r for r in records if r['part'] == product]
        component = {'part': catalyst, 'usage': str(quantity), 'raw_part': catalyst}
        changed = False
        if matched:
            definitions = {(value(r)['use'], tuple(sorted((c['part'], Decimal(c['usage'])) for c in value(r)['components']))) for r in matched}
            if len(definitions) != 1 or any(value(r)['use'] != '사용' for r in matched):
                raise WorkflowError('BOM_CONFLICT', f'{product}: 기존 제품의 BOM 구성·사용구분을 먼저 확인해 주세요.')
            if any(value(r).get('supplier', '').strip() and supplier_name(value(r)['supplier']) != supplier for r in matched):
                raise WorkflowError('BOM_SUPPLIER', f'{product}: 기존 제품의 촉매사와 다릅니다.')
            current = next((c for c in value(matched[0])['components'] if c['part'] == catalyst), None)
            if current and Decimal(current['usage']) != quantity:
                raise WorkflowError('BOM_USAGE_CONFLICT', f'{product}: 이미 등록된 촉매의 소요량은 {current["usage"]}입니다. 기존 소요량 변경은 BOM 수정본으로 반영해 주세요.')
            if not current:
                if any(len(value(r)['components']) >= 4 for r in matched):
                    raise WorkflowError('BOM_LIMIT', f'{product}: 제품별 촉매는 4종까지 등록할 수 있습니다.')
                for r in matched:
                    value(r)['components'].append(deepcopy(component))
                    if not value(r).get('supplier'): value(r)['supplier'] = supplier
                    r['evidence']['_manual_addition'] = {'product': product, 'catalyst': catalyst, 'usage': str(quantity)}
                changed = True
            present = {value(r).get('customer', '').strip() for r in matched}
            new_customers = [c for c in customers if c not in present]
            template = value(matched[0])
        else:
            new_customers = customers or ['']
            template = {'kind': 'bom', 'supplier': supplier, 'use': '사용', 'components': [component]}
        for customer in new_customers:
            if len(records) >= 20000: raise WorkflowError('BOM_LIMIT', 'BOM은 20,000행까지 등록할 수 있습니다.')
            normalized = {**deepcopy(template), 'customer': customer, 'supplier': template.get('supplier') or supplier}
            records.append({'ordinal': max((r['ordinal'] for r in records), default=-1)+1,
                'sheet': '화면에서 추가', 'row_number': len(records)+1, 'part': product, 'quantity': None,
                'evidence': {'_normalized': {'label': '화면에서 추가한 BOM', 'value': normalized}}})
            changed = True
        return changed

    def save_many(self, month, revision, catalyst, supplier, products):
        catalyst = catalyst.strip().upper()
        if catalyst.startswith('R600'): catalyst = catalyst[4:]
        if not PART.fullmatch(catalyst): raise WorkflowError('BOM_PART', '촉매 품번을 확인해 주세요.')
        supplier = selected_supplier(supplier)
        if not products or len(products)>100: raise WorkflowError('BOM_PRODUCTS', '제품은 1개부터 100개까지 추가할 수 있습니다.')
        keys=[e['product'].strip().upper() for e in products]
        if len(keys)!=len(set(keys)): raise WorkflowError('BOM_PRODUCT_DUPLICATE', '같은 제품은 한 번만 입력하고 그 안에서 고객사를 추가해 주세요.')
        before, source = self.current(month)
        Imports.revision(before, revision)
        if source and source.get('status') != 'ready':
            raise WorkflowError('BOM_SOURCE', '현재 BOM 원본의 확인할 항목을 먼저 처리해 주세요.')
        masters = Masters(self.store)
        overview = masters.overview(month)
        head = next((v['id'] for v in overview['versions'] if v['role'] == 'bom_master'), None)
        if not source and (head or any(c['role'] == 'bom_master' for c in overview['candidates'])):
            raise WorkflowError('BOM_BASE_REQUIRED', '저장된 BOM이 아직 이번 달에 적용되지 않았습니다. 품목 추가를 취소하고 기존 BOM을 먼저 이번 달에 적용해 주세요.')
        records = deepcopy((source or {}).get('records', []))
        allowed_customers = Choices(self.store).active('customer')
        changed = False
        for entry in products:
            changed = self.add_product(records, entry, catalyst, supplier, allowed_customers) or changed
        if not changed: raise WorkflowError('BOM_DUPLICATE', '모두 이미 등록된 촉매·제품·고객사 연결입니다. 중복 저장하지 않습니다.')
        payload = {'records': records, 'origin': (source or {}).get('origin'), 'previous_version': head,
                   'base_source': {k: source[k] for k in ('id', 'sha256', 'filename') if k in source} if source else None}
        # Retain the raw original integrity check when the base is an imported file.
        if source and not source.get('master_version'):
            payload['origin'] = {k: source[k] for k in ('id', 'file_id', 'filename', 'sha256')}
        with self.store.connect(write=True) as conn:
            current = self.store.read(conn, month); Imports.revision(current, revision)
            h = conn.execute("SELECT id,version FROM master_version WHERE role='bom_master' ORDER BY version DESC LIMIT 1").fetchone()
            if (h['id'] if h else None) != head:
                raise WorkflowError('MASTER_CONFLICT', 'BOM 기준이 변경됐습니다. 최신 내용을 다시 확인해 주세요.', 409)
            version_id = uuid4().hex
            conn.execute('INSERT INTO master_version VALUES(?,?,?,?,?,?,?,?)', (version_id, 'bom_master', h['version']+1 if h else 1,
                month, None, f'화면 추가: {catalyst} → 제품 {len(products)}종', json.dumps(payload, ensure_ascii=False), now()))
            conn.execute('INSERT INTO draft_master VALUES(?,?,?) ON CONFLICT(draft_id,role) DO UPDATE SET version_id=excluded.version_id', (current['id'], 'bom_master', version_id))
            conn.execute('UPDATE draft SET revision=revision+1,updated_at=? WHERE id=?', (now(), current['id']))
            draft = self.store.read(conn, month)
            self.store.audit(conn, {**draft, 'master_version': version_id, 'products': keys, 'catalyst': catalyst}, 'bom_entry_applied', current)
        return {'draft': draft, 'version_id': version_id}
