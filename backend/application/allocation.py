"""Auditable Heesung allocation preview. Never creates a final closing version."""
from collections import Counter, defaultdict
from copy import deepcopy
from decimal import Decimal, ROUND_HALF_UP, localcontext
from io import BytesIO
import hashlib
import json

from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill

from backend.adapters.allocation import HEADERS, ROLE
from backend.application.basis import Basis, normalized, source_ref
from backend.application.imports import Imports
from backend.application.holds import Holds
from backend.application.reconciliation import Reconciliation
from backend.application.dependencies import digest
from backend.domain.errors import WorkflowError

RULE_VERSION = 'heesung-allocation-3'
HEESUNG = {'희성', '희성촉매'}


def pool_fingerprint(basis, reconciliation, part):
    return digest({'rule': RULE_VERSION, 'basis': basis['part_fingerprints'].get(part),
                   'source': reconciliation['part_fingerprints'].get(part)})


def rounded_allocation(total, weights):
    """Half-up first; preserve the total with deterministic largest-weight correction."""
    if total < 0 or total != total.to_integral_value() or not weights or any(v < 0 for v in weights.values()):
        raise WorkflowError('INVALID_ALLOCATION', '배분 총량과 납품 비율을 확인해 주세요.')
    if len(weights) == 1:
        destination = next(iter(weights))
        return {destination: {'weight': str(weights[destination]), 'ratio': '1', 'unrounded': str(total), 'rounded': str(total), 'correction': '0', 'quantity': str(total)}}
    denominator = sum(weights.values(), Decimal(0))
    if denominator == 0: raise WorkflowError('ZERO_WEIGHT', '여러 마감처의 납품 수량이 모두 0이어서 비율을 계산할 수 없습니다.')
    with localcontext() as ctx:
        ctx.prec = 50
        rows = {}
        for dest, weight in sorted(weights.items()):
            exact = total * weight / denominator; rounded = exact.quantize(Decimal(1), rounding=ROUND_HALF_UP)
            rows[dest] = {'weight': str(weight), 'ratio': str(weight / denominator), 'unrounded': str(exact), 'rounded': str(rounded), 'correction': '0', 'quantity': str(rounded)}
        remaining = total - sum((Decimal(r['quantity']) for r in rows.values()), Decimal(0))
        # At most half the number of rows. Never adjust a zero-weight destination
        # or create negative quantities when a tiny pool is split many ways.
        for dest in sorted(weights, key=lambda d: (-weights[d], d)):
            if not remaining: break
            if weights[dest] == 0: continue
            r = rows[dest]; current = Decimal(r['quantity'])
            delta = remaining if remaining > 0 else -min(current, -remaining)
            r['correction'] = str(delta); r['quantity'] = str(current + delta); remaining -= delta
        assert remaining == 0
        return rows


def apply_splits(rows, inputs):
    """A shared raw total must be completely partitioned; never copy it to each plant."""
    overrides = {n['key']: n for n in inputs if n['kind'] == '공장수량'}
    candidates = {r['route_id']: r for r in rows if r['status'] == 'factory_quantities_needed'}
    unknown = set(overrides) - set(candidates)
    if unknown: raise WorkflowError('SPLIT_ROUTE_CHANGED', '공장 수량 입력의 경로가 현재 공장 구분 대상과 다릅니다. 새 양식을 사용해 주세요.')
    # Connected components support any number of factories; partially overlapping
    # source sets remain unresolved because totals alone cannot prove ownership.
    keys = lambda r: frozenset((e['batch_id'], e['ordinal'], e['metric']) for e in r['stock_evidence'])
    groups = defaultdict(list)
    for r in candidates.values(): groups[keys(r)].append(r)
    for source_keys, group in groups.items():
        if not any(r['route_id'] in overrides for r in group): continue
        if any(source_keys & other for other in groups if other != source_keys):
            raise WorkflowError('SPLIT_OVERLAP', '공장별 원본 행이 부분 중복됩니다. 집계 지점을 먼저 정리해 주세요.')
        if any(r['route_id'] not in overrides for r in group):
            raise WorkflowError('SPLIT_INCOMPLETE', '같은 원본에 연결된 모든 공장의 수량을 입력해 주세요. 0도 명시해야 합니다.')
        evidence = group[0]['stock_evidence']
        if not evidence or any(e['quantity'] is None or Decimal(e['quantity']) < 0 for e in evidence):
            raise WorkflowError('SPLIT_SOURCE_REVIEW', '공장 수량을 구분하기 전에 원본 수량을 확인해 주세요.')
        # Other pending reasons (e.g. negative adjustments) must not be erased.
        if any(len(r['messages']) != 1 for r in group):
            raise WorkflowError('SPLIT_SOURCE_REVIEW', '공장 구분 외의 수량 확인 사항을 먼저 해결해 주세요.')
        total = sum((Decimal(e['quantity']) for e in evidence), Decimal(0))
        if sum((Decimal(overrides[r['route_id']]['quantities']['공장별납품수량']) for r in group), Decimal(0)) != total:
            raise WorkflowError('SPLIT_TOTAL_MISMATCH', '공장별 납품 수량 합계가 중복 제거한 원본 총량과 다릅니다.')
        for r in group:
            n = overrides[r['route_id']]; r['product_quantity'] = n['quantities']['공장별납품수량']; r['status'] = 'linked'
            r['split_evidence'] = n
            for c in r['components']:
                if c['status'] == 'separate_evidence_required': continue
                c['status'] = 'linked'; c['contribution'] = str(Decimal(r['product_quantity']) * Decimal(c['usage']))


def calculate(basis, inputs):
    routes = deepcopy(basis['rows']); apply_splits(routes, inputs)
    pools = {n['key']: n for n in inputs if n['kind'] == '촉매총량'}
    components = defaultdict(list)
    for route in routes:
        for c in route['components']:
            components[c['part']].append({'route_id': route['route_id'], 'product': route['product'], 'supplier': route['supplier'],
                'plant': route['plant'], 'path': route['path'], 'basis_kind': route.get('basis_kind'),
                'stock_evidence': route['stock_evidence'], 'bom_evidence': route['bom_evidence'],
                'split_evidence': route.get('split_evidence'), **c})
    if set(pools) - set(components): raise WorkflowError('POOL_PART_CHANGED', '총량 입력의 촉매가 현재 BOM·경로에 없습니다.')
    result = []
    for part, entries in sorted(components.items()):
        row = {'part': part, 'status': 'ready', 'messages': [], 'components': entries, 'plants': [], 'destinations': [], 'pool': pools.get(part),
               'available': None, 'held': None, 'closing_total': None, 'balance': None}
        result.append(row)
        def pending(status, message): row['status'] = status; row['messages'].append(message)
        if any(e['supplier'] not in HEESUNG for e in entries):
            pending('supplier_rule_pending', '유미코아 등은 촉매사 마감 양식의 수량 기준으로 연결할 단계입니다. 희성 비율을 자동 적용하지 않습니다.'); continue
        if any(e.get('status') != 'linked' or e['contribution'] is None or not e['destination'] for e in entries):
            pending('basis_incomplete', '이 촉매의 모든 제품·마감처 수량 근거가 연결되어야 계산합니다.'); continue
        weights = defaultdict(Decimal); actual = defaultdict(Decimal)
        plant_weights = defaultdict(Decimal)
        for e in entries:
            (actual if e['basis_kind'] == 'actual_receipt' else weights)[e['destination']] += Decimal(e['contribution'])
            if e['basis_kind'] != 'actual_receipt':
                plant_weights[(e['destination'], e['plant'])] += Decimal(e['contribution'])
        if set(weights) & set(actual):
            pending('basis_kind_conflict', '같은 마감처에 실제 입고와 일반 비율 근거가 섞여 있습니다.'); continue
        # Ratios remain inspectable without claiming any closing quantity.
        denominator = sum(weights.values(), Decimal(0))
        row['weights'] = {d: str(q) for d, q in weights.items()}
        row['actual_receipts'] = {d: str(q) for d, q in actual.items()}
        row['ratios'] = {d: str(q / denominator) if denominator else ('1' if len(weights) == 1 else None) for d, q in weights.items()}
        row['plant_basis'] = [{'destination': d, 'plant': p, 'weight': str(q),
                              'ratio': str(q / denominator) if denominator else None}
                             for (d, p), q in sorted(plant_weights.items())]
        if part not in pools:
            pending('pool_required', '전월 이월·당월 입고·조정·미마감 보류 수량을 근거와 함께 확인해야 합니다.'); continue
        q = pools[part]['quantities']; available = sum((Decimal(q[k]) for k in ('전월이월', '당월입고', '조정')), Decimal(0)); held = Decimal(q['미마감보류'])
        fixed = sum(actual.values(), Decimal(0)); remaining = available - held - fixed
        row.update(available=str(available), held=str(held))
        if remaining < 0 or any(v != v.to_integral_value() for v in actual.values()):
            pending('pool_conflict', '총량·보류·실제 입고 촉매 수량이 맞지 않습니다. 글로비스 수량을 줄여 맞추지 않습니다.'); continue
        if not weights and remaining:
            pending('hold_required', '일반 배분 마감처가 없는 잔량입니다. 실제 입고 외 수량의 미마감 처리를 확인해 주세요.'); continue
        try: allocated = rounded_allocation(remaining, plant_weights) if plant_weights else {}
        except WorkflowError as exc:
            pending('weight_required', exc.message); continue
        row['plants'] = [{'destination': d, 'plant': p, 'kind': '일반 비율 배분', **v} for (d, p), v in allocated.items()]
        row['plants'] += [{'destination': d, 'plant': d, 'kind': '실제 입고', 'quantity': str(v), 'correction': '0', 'ratio': None} for d, v in sorted(actual.items())]
        # ERP totals are derived from rounded detailed results, never allocated again.
        totals = defaultdict(lambda: {'quantity': Decimal(0), 'correction': Decimal(0)})
        for item in row['plants']:
            t = totals[item['destination']]
            t['quantity'] += Decimal(item['quantity']); t['correction'] += Decimal(item['correction'])
        row['destinations'] = [{'destination': d, 'kind': '실제 입고' if d in actual else '상세 공장 합계',
                                **{k: str(v) for k, v in t.items()}} for d, t in sorted(totals.items())]
        closing = sum((Decimal(v['quantity']) for v in row['destinations']), Decimal(0))
        row.update(closing_total=str(closing), balance=str(available - closing - held))
    return {'rows': result, 'status_counts': dict(Counter(r['status'] for r in result)),
            'unmapped_routes': [{'route_id': r['route_id'], 'product': r['product'], 'status': r['status']} for r in routes if not r['components'] and r['status'] != 'no_catalyst'],
            'notice': '희성 마감 수량의 계산 검토입니다. 미확인 품목은 합계에서 숨기지 않고 별도 표시합니다. 월 마감 확정·최종 엑셀 출력은 아직 실행하지 않습니다.'}


class Allocation:
    def __init__(self, store): self.store = store

    def preview(self, month):
        basis = Basis(self.store).preview(month); imports = Imports(self.store)
        reconciliation = Reconciliation(self.store).preview(month)
        if reconciliation['revision'] != basis['revision']:
            raise WorkflowError('REVISION_CONFLICT', '원천 조회 중 자료가 변경되었습니다.', 409)
        source_rows = {r['part']: r for r in reconciliation['rows']}
        batch = next((b for b in imports.list(month) if b['role'] == ROLE and b['selected']), None)
        inputs = []; input_ref = None; input_issues = {}
        if batch:
            imports.original(month, batch['id']); batch = imports.detail(month, batch['id'])
            if batch['status'] != 'ready': raise WorkflowError('SOURCE_NOT_READY', '배분입력의 읽기 검산을 확인해 주세요.')
            input_ref = {k: batch[k] for k in ('id', 'sha256', 'filename')}
            for r in batch['records']:
                n = {**normalized(r), 'evidence': source_ref(batch, r)}
                if n['kind'] == '공장수량' and n['fingerprint'] != basis['input_fingerprint']:
                    raise WorkflowError('ALLOCATION_BASIS_CHANGED', 'BOM·경로·수불·입고 기준이 변경되었습니다. 새 양식으로 수량 근거를 다시 확인해 주세요.', 409)
                if n['kind'] == '촉매총량':
                    part = n['key']; source = source_rows.get(part); q = n['quantities']
                    if n['fingerprint'] != pool_fingerprint(basis, reconciliation, part):
                        input_issues[part] = ('pool_basis_changed', '이 촉매의 원천·납품 기준이 바뀌었거나 이전 양식입니다. 새 양식으로 총량 근거를 다시 확인해 주세요.')
                    elif not source or source['status'] != 'matched':
                        input_issues[part] = ('pool_source_review', '촉매사 이월·출하와 ERP·장부의 원천 차이를 먼저 해결해야 합니다.')
                    elif (Decimal(q['전월이월']) != Decimal(source['supplier_prior']) or
                          Decimal(q['당월입고']) != Decimal(source['supplier_incoming'])):
                        input_issues[part] = ('pool_source_review', '입력한 전월 이월·당월 입고가 대조한 원천 구성과 다릅니다. 총량만 맞춰 적용하지 않습니다.')
                inputs.append(n)
        hold_pools, hold_states, hold_fingerprint = Holds(self.store).pools(month, basis)
        conflicts={n['key'] for n in inputs if n['kind']=='촉매총량' and n['key'] in hold_states}
        inputs=[n for n in inputs if not (n['kind']=='촉매총량' and n['key'] in conflicts)]
        inputs.extend(n for n in hold_pools if n['key'] not in conflicts)
        result = calculate(basis, inputs)
        for row in result['rows']:
            if row['part'] in conflicts:
                row.update(status='pool_input_conflict', plants=[], destinations=[], closing_total=None, balance=None)
                row['messages'].append('배분 입력 파일과 월별 보류 내역에 같은 촉매 총량이 있습니다. 중복 입력을 정리해 주세요.')
            elif row['part'] in input_issues:
                status, message = input_issues[row['part']]
                row.update(status=status, plants=[], destinations=[], closing_total=None, balance=None)
                row['messages'].append(message)
            elif hold_states.get(row['part'])=='stale':
                row.update(status='hold_basis_changed', plants=[], destinations=[], closing_total=None, balance=None)
                row['messages'].append('원천·납품 기준이 변경되어 기존 보류 내역을 적용하지 않았습니다. 최신 기준으로 확인 후 저장해 주세요.')
        if self.store.get(month)['revision'] != basis['revision']: raise WorkflowError('REVISION_CONFLICT', '계산 중 자료가 변경되었습니다. 다시 검토해 주세요.', 409)
        result['status_counts'] = dict(Counter(r['status'] for r in result['rows']))
        fingerprint = hashlib.sha256(json.dumps({'basis': basis['input_fingerprint'], 'source': reconciliation['input_fingerprint'], 'input': input_ref, 'holds':hold_fingerprint, 'decisions':[n['hold_decision']['id'] for n in hold_pools], 'rule': RULE_VERSION}, sort_keys=True).encode()).hexdigest()
        result.update(month=month, revision=basis['revision'], input_fingerprint=fingerprint, basis_fingerprint=basis['input_fingerprint'], rule_version=RULE_VERSION, sources=basis['sources'], quantity_source=input_ref)
        result['quantity_sources'] = reconciliation['sources']
        return result

    def template(self, month):
        basis = Basis(self.store).preview(month)
        reconciliation = Reconciliation(self.store).preview(month)
        if reconciliation['revision'] != basis['revision']:
            raise WorkflowError('REVISION_CONFLICT', '양식 생성 중 원천이 변경되었습니다.', 409)
        book = Workbook(); sheet = book.active; sheet.title = '배분입력'; sheet.append(HEADERS)
        for r in basis['rows']:
            if r['status'] == 'factory_quantities_needed':
                sheet.append([month, basis['input_fingerprint'], '공장수량', r['route_id'], None, None, None, None, None, None, None, None])
        parts = sorted({c['part'] for r in basis['rows'] if r['supplier'] in HEESUNG for c in r['components']})
        for part in parts: sheet.append([month, pool_fingerprint(basis, reconciliation, part), '촉매총량', None, part])
        guide = book.create_sheet('작성안내')
        for line in [
            '희성 배분 수량 확인 양식 — 수량은 공란으로 내려받습니다. 확인된 0만 직접 입력하세요.',
            '공장수량: 동일 원본에 묶인 모든 경로의 당월 납품 수량을 입력합니다. 합계는 원본 수량과 같아야 합니다.',
            '촉매총량: 전월이월 + 당월입고 + 조정 = 마감 수량 + 미마감보류. 숫자 4칸과 사유·근거를 모두 입력합니다.',
            '미마감보류에는 글로비스 미입고분 등 이번 달에 마감하지 않을 수량을 포함합니다. 임의로 0을 입력하지 마세요.',
            '당월입고·전월이월은 촉매사 자료와 ERP·이월 장부의 차이를 대조한 값을 입력하고 근거에 기록합니다.',
            '조정은 근거가 있는 증감만 입력합니다. 맞추기 위한 임의 수량을 입력하지 마세요.',
            '일반 배분: 총량 - 미마감보류 - 글로비스 실제 입고×BOM을 제품 납품×BOM 비율로 배분합니다.',
            '수량을 입력하지 않은 행은 미확인입니다. 일부 행만 입력할 수 있지만 부분 입력은 확정 자료가 아닙니다.',
            '촉매총량의 연결근거ID는 촉매별 원천·납품 기준에 연결됩니다. 관련 원천 변경 시 새 양식을 사용하세요.',
            '이월·입고는 원천 구성과 일치해야 합니다. 원천 차이는 이 양식의 조정으로 해제하지 않습니다.',
            '유미코아는 별도 마감 양식 연결 단계에서 처리합니다.',
        ]: guide.append([line])
        routes = book.create_sheet('공장수량근거'); routes.append(['경로번호', '제품', '납품경로', '공장', '마감처', '원본', '시트', '행', '수량항목', '원본수량'])
        for r in basis['rows']:
            if r['status'] == 'factory_quantities_needed':
                for e in r['stock_evidence']: routes.append([r['route_id'], r['product'], r['path'], r['plant'], r['destination'], e['filename'], e['sheet'], e['row_number'], e['metric'], e['quantity']])
        for s in (sheet, routes):
            s.auto_filter.ref = s.dimensions
            for cell in s[1]: cell.font = Font(color='FFFFFF', bold=True); cell.fill = PatternFill('solid', fgColor='234B61')
            for col in s.columns: s.column_dimensions[col[0].column_letter].width = 22
        sheet.column_dimensions['B'].width = 68; sheet.column_dimensions['L'].width = 65; guide.column_dimensions['A'].width = 125
        # Text from source workbooks must never become a formula in generated files.
        for s in book:
            for row in s:
                for cell in row:
                    if isinstance(cell.value, str): cell.data_type = 's'
        stream = BytesIO(); book.save(stream); book.close(); return stream.getvalue()
