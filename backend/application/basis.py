"""Read-only route/BOM linkage preview; never allocate a catalyst closing pool."""
from collections import Counter, defaultdict
from decimal import Decimal
import hashlib
import json

from backend.application.imports import Imports
from backend.domain.errors import WorkflowError
from backend.application.dependencies import digest, scoped_evidence
from backend.domain.destinations import canonical_destination

RULE_VERSION = 'basis-link-3'
# Existing reviewed warehouse aliases. Unlisted routes remain explicitly pending.
WAREHOUSES = {
    '현대 위아': ('위아-평택', '위아-서산1', '위아-서산2'),
    '세종공업': ('세종공업(화성)',), '세정공업': ('세정',),
    '포레시아 영천': ('포레시아-영천',), '포레시아 장안': ('포레시아-장안',),
    '포레시아 광주': ('포레시아-광주',), '아산엔진': ('현대-아산(화성)',),
    '울산엔진': ('현대-울산(화성)',), '광명엔진': ('기아-광명(화성)',),
}


def normalized(row):
    n=row['evidence']['_normalized']['value']
    return {**n,'destination':canonical_destination(n['destination'])} if 'destination' in n else n


def source_ref(batch, row):
    return {'batch_id': batch['id'], 'filename': batch['filename'], 'ordinal': row['ordinal'], 'sheet': row['sheet'], 'row_number': row['row_number']}


class Basis:
    def __init__(self, store): self.store = store

    def preview(self, month):
        before = self.store.get(month); imports = Imports(self.store)
        sources = imports.effective_sources(month, ('bom_master','route_master','product_stock','semi_stock','glovis_receipts'))
        missing = [r for r in ('bom_master', 'route_master') if r not in sources]
        if missing: raise WorkflowError('MASTER_REQUIRED', 'BOM과 통합 경로표를 등록하고 이번 달 기준으로 채택해 주세요.')
        if any(b['status']!='ready' for b in sources.values()): raise WorkflowError('SOURCE_NOT_READY', '채택 자료의 검산 상태를 확인해 주세요.')
        result = link(sources)
        if self.store.get(month)['revision'] != before['revision']:
            raise WorkflowError('REVISION_CONFLICT', '연결 검토 중 자료가 변경됐습니다. 다시 검토해 주세요.', 409)
        result.update(month=month, revision=before['revision'], rule_version=RULE_VERSION,
                      sources={role: {'id': b['id'], 'filename': b['filename'], 'sha256': b['sha256']} for role, b in sources.items()})
        result['input_fingerprint'] = hashlib.sha256(json.dumps({'sources': result['sources'], 'rule_version': RULE_VERSION}, sort_keys=True).encode()).hexdigest()
        parts = {c['part'] for r in result['rows'] for c in r['components']}
        result['part_fingerprints'] = {part: digest({'rule': RULE_VERSION,
            'routes': scoped_evidence([r for r in result['rows'] if any(c['part'] == part for c in r['components'])], sources)}) for part in parts}
        return result


def link(sources):
    bom = defaultdict(list)
    for row in sources['bom_master']['records']: bom[row['part']].append(row)
    stock = defaultdict(list)
    for role in ('product_stock', 'semi_stock'):
        if role in sources:
            for row in sources[role]['records']: stock[(role, row['part'])].append(row)
    glovis = defaultdict(list)
    for row in sources.get('glovis_receipts', {}).get('records', []): glovis[row['part']].append(row)
    rows = []; owners = defaultdict(list)
    for route in sources['route_master']['records']:
        config = normalized(route); product = route['part']; path = config['path']
        if not config.get('included',True): continue
        linked = {'route_id': config['route_id'], 'supplier': config['supplier'], 'product': product, 'path': path, 'plant': config['plant'], 'destination': config['destination'],
                  'route_state': config['state'], 'note': config['note'], 'route_evidence': source_ref(sources['route_master'], route),
                  'bom_evidence': [], 'stock_evidence': [], 'components': [], 'product_quantity': None, 'status': 'linked', 'messages': []}
        rows.append(linked)
        def pending(status, message): linked['status'] = status; linked['messages'].append(message)
        if product not in bom:
            pending('bom_missing', '동일한 M/H·접미사의 BOM이 없습니다. 유사 품번으로 대체하지 않습니다.'); continue
        variants = bom[product]
        # Parser already rejects inconsistent versions; check again at the boundary.
        definitions = {(normalized(r)['use'], tuple(sorted((c['part'], Decimal(c['usage'])) for c in normalized(r)['components']))) for r in variants}
        if len(definitions) != 1:
            pending('bom_conflict', '동일 제품의 BOM 구성이 서로 다릅니다.'); continue
        linked['bom_evidence'] = [source_ref(sources['bom_master'], r) for r in variants]
        composition = normalized(variants[0]); linked['components'] = [dict(c) for c in composition['components']]
        if composition['use'] == '미사용': pending('no_catalyst', '촉매 미사용 기준입니다. 제품·경로 이력은 보존합니다.'); continue
        if config['state'] not in ('설정 완료', '경로 설정 완료', 'BOM 기준 등록 완료', '설정 완료 / 단산 경로', '단산 / 이력 보존'):
            pending('route_review', '경로의 처리 상태를 확인해야 합니다. 연결된 촉매의 배분을 보류합니다.'); continue
        metric = None; matches = []; role = None
        if path in ('글로비스', '글로비스-전주') or config.get('source_role')=='glovis_receipts':
            role = 'glovis_receipts'
            # Explicit Glovis product identity bridge, never applied to stock/BOM.
            bare = product[1:] if product.startswith('M') else product
            bare = bare[:-4] if bare.endswith('_CKD') else bare
            matches = glovis.get(bare, [])
            if role not in sources:
                pending('source_missing', '글로비스 실제 입고 자료가 필요합니다. 수불 이동으로 대신하지 않습니다.'); continue
            metric = '실제 입고수량'
            if not matches: linked['messages'].append('채택한 전체 월 입고 명세에 해당 제품 거래가 없어 실제 입고 0으로 연결합니다.')
        elif config.get('source_role') in ('product_stock','semi_stock'):
            role=config['source_role'];metric=config['metric']
            matches=[r for r in stock.get((role,product),[]) if normalized(r)['warehouse'] in config['warehouses']]
        elif 'source_role' in config:
            pending('basis_pending', '프로그램 기준에서 집계 자료·창고·수량 항목을 지정해 주세요.'); continue
        elif path.startswith('당진 경유 /'):
            role = 'semi_stock'; metric = '출고/적송처리'
            matches = [r for r in stock.get((role, product), []) if normalized(r)['warehouse'] == '원자재(창고+라인)']
        elif path in WAREHOUSES:
            role = 'product_stock'; metric = '입고/이동처리'
            matches = [r for r in stock.get((role, product), []) if normalized(r)['warehouse'] in WAREHOUSES[path]]
        else:
            pending('basis_pending', '기존 상세 유보 경로입니다. 수량 항목을 임의 선택하지 않습니다.'); continue
        if role not in sources:
            pending('source_missing', '해당 제품/반제품 수불 원본을 채택해 주세요.'); continue
        if not matches and role != 'glovis_receipts':
            pending('basis_missing', '해당 집계 지점의 품번 행이 없습니다. 0으로 대체하지 않습니다.'); continue
        total = Decimal(0)
        for source in matches:
            info = normalized(source)
            quantity = source['quantity'] if role == 'glovis_receipts' else info['metrics'].get(metric)
            ref = {**source_ref(sources[role], source), 'warehouse': info.get('warehouse'), 'metric': metric, 'quantity': quantity}
            linked['stock_evidence'].append(ref)
            owners[(ref['batch_id'], ref['ordinal'], metric)].append(linked)
            if quantity is None:
                pending('quantity_missing', '선택할 수량 열이 없거나 비었습니다.'); continue
            total += Decimal(quantity)
            if Decimal(quantity) < 0: pending('quantity_review', '음수 수량을 보존했습니다. 배분 근거 적용을 검토해야 합니다.')
            if role == 'semi_stock' and info['metrics'].get('출고/이동처리') not in (None, '0'):
                pending('quantity_review', '출고 이동처리 수량도 있습니다. 적송과 함께 임의 합산하지 않습니다.')
            if role == 'product_stock' and info['metrics'].get('입고/기타입고') not in (None, '0'):
                linked['messages'].append('기타입고 조정은 원문에 보존하며 당월 이동 수량에 자동 합산하지 않습니다.')
        if linked['status'] == 'linked': linked['product_quantity'] = str(total)
        linked['basis_kind'] = 'actual_receipt' if role == 'glovis_receipts' else 'allocation_weight'

    # Generic ownership check: any product can serve multiple factories. A
    # single undivided source quantity must not be counted in each factory.
    for shared in owners.values():
        unique = {r['route_id']: r for r in shared}
        if len(unique) > 1:
            for row in unique.values():
                row['status'] = 'factory_quantities_needed'; row['product_quantity'] = None
                msg = '동일 원본 수량이 여러 공장에 연결됩니다. 공장별 납품 수량 구분이 필요합니다.'
                if msg not in row['messages']: row['messages'].append(msg)
    for row in rows:
        for component in row['components']:
            component['destination'] = row['destination']; component['contribution'] = None
            # A structured catalyst-specific destination is higher priority than
            # the product path. Direct supply requires its own quantity evidence.
            if ':' in row['destination']:
                mapping = {k.strip(): v.strip() for k, v in (line.split(':', 1) for line in row['destination'].splitlines() if ':' in line)}
                dest = mapping.get(component['part'])
                component['destination'] = dest.strip() if dest else None
                if not dest or (row.get('basis_kind') == 'actual_receipt' and '글로비스' not in dest):
                    component['status'] = 'separate_evidence_required'; continue
            component['status'] = row['status']
            if row['status'] == 'linked': component['contribution'] = str(Decimal(row['product_quantity']) * Decimal(component['usage']))
    return {'rows': rows, 'status_counts': dict(Counter(r['status'] for r in rows)), 'route_count': len(rows),
            'notice': '제품×BOM의 배분 근거 연결입니다. 촉매 마감 총량 배분·금액 계산·확정은 실행하지 않습니다.'}
