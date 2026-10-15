"""Monthly review, append-only edits and immutable, reproducible closing versions.

This is the integrated workflow. The earlier read-only previews remain available
as independent evidence views; they are not a second source of closing totals.
"""
from collections import Counter, defaultdict
from copy import deepcopy
from decimal import Decimal, ROUND_HALF_UP, InvalidOperation
import json
import re
from uuid import uuid4

from backend.adapters.storage import now
from backend.application.allocation import calculate, apply_splits
from backend.application.basis import Basis, normalized, source_ref
from backend.application.dependencies import digest, record_content
from backend.application.holds import Holds, validate_lines
from backend.application.imports import Imports
from backend.application.pricing import resolve_price
from backend.application.reconciliation import Reconciliation
from backend.domain.errors import WorkflowError

RULE = 'monthly-closing-1'
KINDS = {'carry', 'source', 'hold', 'quantities', 'prices', 'mapping', 'splits', 'statement'}


def quantity(value, signed=False):
    if not isinstance(value, str) or not re.fullmatch(r'-?\d{1,12}' if signed else r'\d{1,12}', value):
        raise WorkflowError('INVALID_QUANTITY', '수량은 정수로 입력해 주세요. 공란과 0은 다릅니다.')
    return str(int(value))


def previous_month(month):
    y, m = map(int, month.split('-'))
    return f'{y-1 if m == 1 else y:04d}-{12 if m == 1 else m-1:02d}'


class Closing:
    def __init__(self, store): self.store = store

    def history(self, month):
        with self.store.connect() as conn:
            d = self.store.read(conn, month)
            return [{**dict(r), 'payload': json.loads(r['payload_json'])} for r in conn.execute(
                'SELECT * FROM monthly_decision WHERE draft_id=? ORDER BY revision DESC', (d['id'],))]

    def snapshots(self, month):
        with self.store.connect() as conn:
            return [dict(r) for r in conn.execute('SELECT id,month,version,revision,fingerprint,created_at FROM closing_snapshot WHERE month=? ORDER BY version DESC', (month,))]

    def snapshot(self, snapshot_id):
        with self.store.connect() as conn:
            r = conn.execute('SELECT * FROM closing_snapshot WHERE id=?', (snapshot_id,)).fetchone()
            if not r: raise WorkflowError('NOT_FOUND', '확정본을 찾을 수 없습니다.', 404)
            return {**dict(r), 'payload': json.loads(r['payload_json'])}

    def preview(self, month):
        before = self.store.get(month)
        imports = Imports(self.store)
        sources = imports.effective_sources(month)
        basis = Basis(self.store).preview(month)
        recon = Reconciliation(self.store).preview(month)
        events = self.history(month); latest = {}
        for e in events: latest.setdefault((e['part'], e['kind']), e)
        with self.store.connect() as conn:
            ref = conn.execute('SELECT snapshot_id FROM carry_reference WHERE draft_id=?', (before['id'],)).fetchone()
        carry_snapshot = self.snapshot(ref[0]) if ref else None
        prior_rows = {r['part']: r for r in carry_snapshot['payload']['rows']} if carry_snapshot else {}
        prior_versions = self.snapshots(previous_month(month))
        carry_changed = bool(carry_snapshot and prior_versions and prior_versions[0]['id'] != carry_snapshot['id'])
        split_fp = digest({'rule': RULE, 'basis': basis['input_fingerprint']})
        split = latest.get(('*', 'splits'))
        split_issues = []
        if split and split['payload'] is not None:
            if split['fingerprint'] != split_fp: split_issues.append('공장별 제품 수량의 원본이 변경되었습니다.')
            else: apply_splits(basis['rows'], split['payload']['lines'])
        route_parts = defaultdict(list)
        for r in basis['rows']:
            for c in r['components']: route_parts[c['part']].append((r, c))
        recon_rows = {r['part']: r for r in recon['rows']}
        prices = defaultdict(list)
        for r in sources.get('price_master', {}).get('records', []): prices[r['part']].append(r)
        policies = sources.get('price_policy', {}).get('records', [])
        opening = defaultdict(lambda: defaultdict(Decimal))
        for r in sources.get('comparison_report', {}).get('records', []):
            n = normalized(r); opening[r['part']][n['destination']] += Decimal(n['prior'])
        if carry_snapshot:
            opening.clear()
            for part, r in prior_rows.items():
                for line in r['hold_lines']: opening[part][line['destination']] += Decimal(line['remaining'])
        legacy_holds = {r['part']: r for r in Holds(self.store).preview(month)['rows']}
        rows = []
        umi_stock = {r['part']: r for r in sources.get('umicore_carryover', {}).get('records', [])}
        all_parts = set(recon_rows) | set(route_parts) | set(prior_rows) | set(umi_stock)
        for part in sorted(all_parts):
            src = deepcopy(recon_rows.get(part, {'part': part, 'supplier': None, 'status': 'source_missing',
                'supplier_prior': None, 'supplier_incoming': None, 'supplier_available': None,
                'ledger_prior': None, 'erp_incoming': None, 'evidence': {}, 'historical_held': None}))
            entries = route_parts[part]
            supplier = src['supplier'] or next((r['supplier'] for r, c in entries), None) or ('유미코아' if part in umi_stock else None)
            if supplier == '희성촉매': supplier = '희성'
            if part not in recon_rows:
                # A BOM-only item absent from adopted complete sources has zero
                # transactions. Missing source files remain unknown, never zero.
                income_role='heesung_shipments' if supplier=='희성' else 'umicore_statement'
                prior_role='heesung_carryover' if supplier=='희성' else 'umicore_carryover'
                src.update(supplier=supplier,supplier_prior='0' if prior_role in sources else None,
                           supplier_incoming='0' if income_role in sources else None,
                           ledger_prior='0' if 'comparison_report' in sources else None,
                           erp_incoming='0' if 'erp_receipts' in sources else None)
                if all(src[k] is not None for k in ('supplier_prior','supplier_incoming','ledger_prior','erp_incoming')): src['status']='matched'
            row = {'part': part, 'supplier': supplier, 'source': src, 'issues': [], 'decisions': {},
                'fingerprints': {}, 'plants': [], 'destinations': [], 'hold_lines': [], 'components': [],
                'prior': src['supplier_prior'], 'incoming': src['supplier_incoming'], 'held': None,
                'closing_total': None, 'amount': None, 'status': 'review',
                'opening_lots': [{**p,'lot_id':digest({'snapshot':carry_snapshot['id'],'part':part,'index':i})} for i,p in enumerate(prior_rows.get(part,{}).get('pending',[])) if Decimal(p['remaining'])] if carry_snapshot else [],
                'opening_by_destination': {d: str(q) for d, q in opening[part].items() if q},
                'destinations_allowed': sorted({c['destination'] for r, c in entries if c.get('destination')} | set(opening[part]))}
            rows.append(row)
            def issue(code, message, source_roles=None): row['issues'].append({'code': code, 'message': message, **({'source_roles':source_roles} if source_roles else {})})
            if supplier not in ('희성','유미코아'): issue('supplier_required', '촉매사 원본 또는 BOM으로 촉매사를 연결해야 합니다.')
            def decision(kind, fp):
                row['fingerprints'][kind] = fp
                e = latest.get((part, kind))
                if not e: return None
                row['decisions'][kind] = {'id': e['id'], 'revision': e['revision'], 'payload': e['payload'], 'current': e['fingerprint'] == fp}
                if e['payload'] is None: return None
                if e['fingerprint'] != fp:
                    issue(kind+'_stale', '저장한 '+{'carry':'이월 수정','source':'원천 선택','hold':'보류 처리','quantities':'수량 수정','prices':'단가 수정','mapping':'마감처 연결','statement':'촉매사 마감 차이 확인'}[kind]+'의 근거가 바뀌었습니다. 다시 검토해 주세요.')
                    return None
                return e['payload']
            raw_fp = digest({'rule': RULE, 'source': recon['part_fingerprints'].get(part),
                             'bom_only_sources': {role: b['sha256'] for role,b in sources.items() if role in ('heesung_shipments','heesung_carryover','umicore_statement','umicore_carryover','erp_receipts','comparison_report')} if part not in recon_rows else None,
                             'carry_snapshot': carry_snapshot['id'] if carry_snapshot else None,
                             'pdf': [record_content(sources['umicore_carryover'], r) for r in sources.get('umicore_carryover', {}).get('records', []) if r['part'] == part],
                             'umi_pdf_present': supplier == '유미코아' and 'umicore_carryover' in sources})
            # Supplier stock PDF is the default. A linked prior finalized version
            # is an independent comparison, not a silent replacement of the PDF.
            if supplier == '유미코아':
                pdf = sources.get('umicore_carryover')
                row['prior'] = str(sum((Decimal(r['quantity']) for r in pdf['records'] if r['part'] == part), Decimal(0))) if pdf else None
            row['original_prior'] = row['prior']
            row['previous_final_held'] = prior_rows.get(part, {}).get('held')
            carry = decision('carry', raw_fp)
            if carry: row['prior'] = carry['quantity']
            source_fp = digest({'raw': raw_fp, 'prior': row['prior']})
            choice = decision('source', source_fp)
            if choice:
                if choice['choice'] == 'erp': row['prior'], row['incoming'] = src['ledger_prior'], src['erp_incoming']
                elif choice['choice'] == 'manual': row['prior'], row['incoming'] = choice['prior'], choice['incoming']
                elif choice['choice'] == 'previous': row['prior'] = row['previous_final_held']
            row['source_choice'] = choice['choice'] if choice else 'supplier'
            if row['prior'] is None or row['incoming'] is None:
                issue('source_missing', '전월 적송 PDF와 당월 원천 수량을 연결해야 합니다.', ([('umicore_carryover' if supplier=='유미코아' else 'heesung_carryover')] if row['prior'] is None and supplier else []) + ([('umicore_statement' if supplier=='유미코아' else 'heesung_shipments')] if row['incoming'] is None and supplier else []))
            elif not choice and ((src['ledger_prior'] is not None and Decimal(row['prior']) != Decimal(src['ledger_prior'])) or
                                (src['erp_incoming'] is not None and Decimal(row['incoming']) != Decimal(src['erp_incoming'])) or
                                row['prior'] != src['supplier_prior'] or
                                (row['previous_final_held'] is not None and Decimal(row['prior']) != Decimal(row['previous_final_held']))):
                issue('source_difference', 'PDF·촉매사·ERP 또는 전월 확정본의 구성이 다릅니다. 적용할 구성을 선택해 주세요.')
            if not choice and src['erp_incoming'] is None:
                issue('source_missing', 'ERP 촉매 입고 자료를 등록해 당월 입고 수량을 대조해 주세요.', ['erp_receipts'])
            if src['status'] == 'supplier_conflict': issue('supplier_conflict', '촉매사가 중복됩니다. 원본 연결을 정리해야 합니다.')
            available = Decimal(row['prior']) + Decimal(row['incoming']) if row['prior'] is not None and row['incoming'] is not None else None
            row['available'] = str(available) if available is not None else None
            if available is not None and available < 0: issue('negative_available', '가용 총량이 음수입니다. 반품·정정 근거를 확인해 주세요.')
            basis_fp = digest({'basis': basis['part_fingerprints'].get(part), 'split': [r.get('split_evidence') for r,c in entries]})
            mapping = decision('mapping', digest({'raw': raw_fp, 'basis': basis_fp}))
            row['automatic_mapping'] = None
            if not mapping and not entries:
                erp_rows = [r for r in sources.get('erp_receipts', {}).get('records', []) if r['part']==part and normalized(r)['included']]
                customers = defaultdict(Decimal)
                for r in erp_rows:
                    for d,q in normalized(r)['by_customer'].items():
                        if q is not None: customers[d] += Decimal(q)
                nonzero = {d:q for d,q in customers.items() if q}
                # The historical ERP explicitly identifies Mobis, which has no
                # detailed engine-factory split. Do not infer plants for OEM sites.
                if len(nonzero)==1 and next(iter(nonzero))=='현대모비스(주)' and next(iter(nonzero.values()))>0:
                    mapping={'lines':[{'destination':'현대 모비스','plant':'모비스','weight':'1'}],
                             'reason':'현재 BOM 밖의 ERP 모비스 단일 마감 실적',
                             'evidence':[source_ref(sources['erp_receipts'],r) for r in erp_rows]}
                    row['automatic_mapping']=mapping
            if mapping:
                row['destinations_allowed'] = sorted(set(row['destinations_allowed']) | {x['destination'] for x in mapping['lines']})
            hold_fp = digest({'source': source_fp, 'choice': choice, 'basis': basis_fp, 'mapping': mapping, 'opening': row['opening_by_destination']})
            hold = decision('hold', hold_fp)
            legacy = legacy_holds.get(part)
            if 'hold' not in row['decisions'] and not choice and not carry and not carry_snapshot and legacy and legacy['decision_status'] == 'current':
                hold = legacy['decision']['payload']
            glovis = any('글로비스' in d for d in row['destinations_allowed'])
            stale_hold = any(i['code'] == 'hold_stale' for i in row['issues']) or bool(
                not hold and legacy and legacy.get('decision') and 'hold' not in row['decisions'])
            row['hold_defaulted'] = False
            # Ordinary items close the entire supplier pool unless an exception
            # was entered. This is a calculation default, not a saved approval.
            # Glovis and outdated saved holds still require an explicit review.
            if not hold and not glovis and not stale_hold:
                hold = {'held': '0', 'default_rule': 'ordinary-full-closing-1',
                    'lines': [{'destination': d, 'opening': row['opening_by_destination'].get(d, '0'),
                        'new_hold': '0', 'released': row['opening_by_destination'].get(d, '0'),
                        'remaining': '0', 'action': '기본 전량 마감',
                        'reason': '별도 미마감 입력 없음', 'evidence': '전월 이월 + 당월 입고 기본 마감'}
                        for d in row['destinations_allowed']],
                    'lot_releases': {lot['lot_id']: lot['remaining'] for lot in row['opening_lots']}}
                row['hold_defaulted'] = True
            row['applied_lot_releases'] = (hold or {}).get('lot_releases', {})
            if hold:
                row['held'] = hold['held']; row['hold_lines'] = hold['lines']
                if available is not None and Decimal(row['held']) > available: issue('hold_exceeds', '보류가 가용 총량보다 큽니다.')
            active = any(Decimal(str(v)) != 0 for v in (row['prior'], row['incoming'], src.get('ledger_prior'), src.get('erp_incoming')) if v is not None)
            active = active or any(c.get('contribution') and Decimal(c['contribution']) for r,c in entries)
            active = active or any(q != 0 for q in opening[part].values())
            row['active'] = bool(active)
            umi_records = [r for r in sources.get('umicore_statement', {}).get('records', []) if r['part'] == part]
            statement_total = umi_records[0]['quantity'] if len(umi_records) == 1 else None
            row['supplier_closing'] = statement_total
            if active and not hold:
                issue('hold_required', '글로비스는 실제 입고된 제품만 마감합니다. 미입고분의 미마감 수량을 확인해 주세요.' if glovis
                      else '이전에 입력한 미마감의 근거가 바뀌었습니다. 미마감 조정에서 다시 확인해 주세요.')
            calc_basis = {'rows': []}
            for route, c in entries:
                copy = deepcopy(route); copy['components'] = [deepcopy(c)]; copy['supplier'] = '희성'
                calc_basis['rows'].append(copy)
            # Explicit, evidenced manual connection is for absent BOM or direct
            # supplied catalysts only. Existing Glovis receipt paths are protected.
            if mapping:
                calc_basis['rows'] = [r for r in calc_basis['rows'] if r.get('basis_kind')=='actual_receipt' and '글로비스' in (r['components'][0].get('destination') or '')]
                for i, x in enumerate(mapping['lines']):
                    calc_basis['rows'].append({'route_id': 'monthly-'+str(i), 'product': part,
                        'supplier': '희성', 'plant': x['plant'], 'path': '이번 달 근거 연결',
                        'status': 'linked', 'stock_evidence': [], 'bom_evidence': [], 'basis_kind': 'ratio',
                        'components': [{'part': part, 'destination': x['destination'], 'status': 'linked', 'usage': '1', 'contribution': x['weight']}]})
            row['mapping_allowed'] = not entries or any(r.get('basis_kind')!='actual_receipt' or c.get('status')=='separate_evidence_required' for r,c in entries)
            row['plant_basis'] = []
            if calc_basis['rows']:
                proposal=calculate(calc_basis,[])['rows'][0]
                row['plant_basis']=[{**p,'kind':'납품 비율','fixed_quantity':None} for p in proposal.get('plant_basis',[])]
                row['plant_basis'] += [{'destination':d,'plant':d,'weight':q,'ratio':None,'kind':'실제 입고','fixed_quantity':q} for d,q in proposal.get('actual_receipts',{}).items()]
            row['components'] = [{'product':r['product'],'route_id':r['route_id'],'plant':r['plant'],'path':r['path'],
                                  'stock_evidence':r['stock_evidence'],'bom_evidence':r['bom_evidence'],**c} for r,c in entries]
            total = available - Decimal(row['held']) if available is not None and row['held'] is not None else None
            allocation_needed = active and total != 0
            if allocation_needed and not mapping and any(c.get('status')!='linked' or c.get('contribution') is None or not c.get('destination') for r,c in entries):
                issue('basis_incomplete', '제품 경로·수불 또는 직사급 촉매의 별도 수량 근거를 연결해야 합니다.')
            statement_review=decision('statement',digest({'source':source_fp,'choice':choice,'hold':hold,'statement':statement_total}))
            row['statement_difference']=str(total-Decimal(statement_total)) if total is not None and statement_total is not None else None
            if supplier == '유미코아' and row['statement_difference'] not in (None,'0') and not statement_review:
                issue('umicore_closing_difference', '유미코아 원문 마감 수량과 보류 처리 후 마감 총량이 다릅니다. 수량 수정 사유를 남겨야 합니다.')
            if allocation_needed and not calc_basis['rows']: issue('mapping_missing', '현재 BOM 밖의 실적입니다. ERP 근거에 따라 이번 달 마감처를 연결해 주세요.')
            if active and total == 0:
                row.update(closing_total='0',amount='0',balance='0')
                actual_total=sum((Decimal(c.get('contribution') or 0) for r,c in entries if r.get('basis_kind')=='actual_receipt' and c.get('destination') and '글로비스' in c['destination']),Decimal(0))
                if actual_total:issue('actual_exceeds_pool','글로비스 실제 입고가 있어 전량 보류로 처리할 수 없습니다.')
                if any(c.get('destination') and '글로비스' in c['destination'] and (r.get('basis_kind')=='actual_receipt' or r.get('path') in ('글로비스','글로비스-전주')) and (c.get('status')!='linked' or c.get('contribution') is None) for r,c in entries):
                    issue('actual_receipts_missing','전량 보류를 확인하기 전에 글로비스 실제 입고 자료를 연결해야 합니다.')
            if allocation_needed and total is not None and total > 0 and calc_basis['rows']:
                calc = calculate(calc_basis, [{'kind': '촉매총량', 'key': part, 'quantities': {'전월이월': row['prior'], '당월입고': row['incoming'], '조정': '0', '미마감보류': row['held']}}])['rows'][0]
                row['components'] = calc['components']
                row['plants'] = calc['plants']
                if calc['status'] != 'ready': issue(calc['status'], ' / '.join(calc['messages']))
            quantity_fp = digest({'hold': hold_fp, 'hold_value': hold, 'basis': basis_fp, 'mapping': mapping})
            edits = decision('quantities', quantity_fp)
            for p in row['plants']: p['automatic_quantity'] = p['quantity']
            if edits:
                for p in row['plants']:
                    edit = next((x for x in edits['lines'] if (x['destination'], x['plant']) == (p['destination'], p['plant'])), None)
                    if edit and edit['quantity'] is not None: p['quantity'] = edit['quantity']; p['modified'] = True
                row['issues'] = [i for i in row['issues'] if i['code'] != 'umicore_closing_difference']
            price_fp = digest({'prices': [record_content(sources['price_master'], r) for r in prices[part]],
                'policies': [record_content(sources['price_policy'], r) for r in policies if r['part'] == part],
                'opening_lots': row['opening_lots'],
                'destinations': sorted({p['destination'] for p in row['plants']} | {x['destination'] for x in row['hold_lines'] if Decimal(x['remaining'])})})
            price_edits = decision('prices', price_fp)
            totals = defaultdict(Decimal); amount = Decimal(0)
            for p in row['plants']:
                totals[p['destination']] += Decimal(p['quantity'])
                price = resolve_price(part, p['destination'], prices, policies)
                e = next((x for x in price_edits['lines'] if x['destination'] == p['destination']), None) if price_edits else None
                p['price'] = e['price'] if e else price['applied_price']; p['price_kind'] = e['price_kind'] if e else price['price_kind']
                p['amount'] = str((Decimal(p['quantity']) * Decimal(p['price'])).quantize(Decimal(1), rounding=ROUND_HALF_UP)) if p['price'] is not None else None
                if p['amount'] is None and Decimal(p['quantity']): issue('price_required', p['destination']+' 적용 단가를 확인해 주세요.')
                if p['amount'] is not None: amount += Decimal(p['amount'])
            row['destinations'] = [{'destination': d, 'quantity': str(q)} for d,q in sorted(totals.items())]
            row['pending'] = []
            for line in row['hold_lines']:
                price = resolve_price(part, line['destination'], prices, policies)
                e = next((x for x in price_edits['lines'] if x['destination'] == line['destination']), None) if price_edits else None
                unit = e['price'] if e else price['applied_price']
                lots=[p for p in row['opening_lots'] if p['destination']==line['destination']]
                if lots:
                    releases=(hold or {}).get('lot_releases',{})
                    for lot in lots:
                        released=releases.get(lot['lot_id'],line['released'] if len(lots)==1 else '0')
                        remaining=Decimal(lot['remaining'])-Decimal(released)
                        old_unit=e['price'] if e else lot['price'];old_kind=e['price_kind'] if e else lot['price_kind']
                        row['pending'].append({**line,'opening':lot['remaining'],'new_hold':'0','released':released,'remaining':str(remaining),
                            'price':old_unit,'price_kind':old_kind,'original_price':lot['price'],'original_price_kind':lot['price_kind'],
                            'amount':str((remaining*Decimal(old_unit)).quantize(Decimal(1),rounding=ROUND_HALF_UP)) if old_unit is not None else None,
                            'origin_lot':lot['lot_id']})
                    if Decimal(line['new_hold']):
                        row['pending'].append({**line,'opening':'0','released':'0','remaining':line['new_hold'],'price':unit,'price_kind':e['price_kind'] if e else price['price_kind'],
                            'amount':str((Decimal(line['new_hold'])*Decimal(unit)).quantize(Decimal(1),rounding=ROUND_HALF_UP)) if unit is not None else None})
                else:
                    row['pending'].append({**line, 'price':unit, 'price_kind':e['price_kind'] if e else price['price_kind'],
                        'amount':str((Decimal(line['remaining'])*Decimal(unit)).quantize(Decimal(1),rounding=ROUND_HALF_UP)) if unit is not None else None})
            for pending in row['pending']:
                if pending['price'] is None and Decimal(pending['remaining']):issue('pending_price_required',pending['destination']+' 보류분 단가를 확인해 주세요.')
            if row['plants']:
                row['closing_total'] = str(sum(totals.values(), Decimal(0))); row['amount'] = str(amount)
                row['balance'] = str(available-Decimal(row['held'])-Decimal(row['closing_total']))
                if Decimal(row['balance']): issue('balance_difference', '수정 후 마감 합계가 총량과 다릅니다. 다른 공장 수량을 자동 변경하지 않습니다.')
            if not active:
                row.update(status='inactive', issues=[], held='0', closing_total='0', amount='0', balance='0')
            else: row['status'] = 'review' if row['issues'] else 'ready'
        issues = [{'part': r['part'], **i} for r in rows for i in r['issues']]
        issues += [{'part': '*', 'code': 'split_stale', 'message': m} for m in split_issues]
        unmapped = [r for r in basis['rows'] if not r['components'] and r['status'] != 'no_catalyst']
        issues += [{'part': r['product'], 'code': 'unmapped_product', 'message': '제품의 촉매 연결을 확인해야 합니다.'} for r in unmapped]
        if carry_changed: issues.append({'part': '*', 'code': 'previous_version_changed', 'message': '전월이 재확정되었습니다. 연결된 이전 버전과 새 버전의 차이를 검토하고 이월 기준을 선택해 주세요.'})
        if self.store.get(month)['revision'] != before['revision']: raise WorkflowError('REVISION_CONFLICT', '계산 중 자료가 바뀌었습니다. 다시 계산해 주세요.', 409)
        source_refs = {role: {k: b[k] for k in ('id', 'filename', 'sha256', 'source_period', 'parser_version')} for role,b in sources.items()}
        result = {'month': month, 'revision': before['revision'], 'finalized': before['finalized'], 'rule_version': RULE,
            'rows': rows, 'issues': issues, 'status_counts': dict(Counter(r['status'] for r in rows)),
            'ready': bool(rows) and not issues and any(r['active'] for r in rows), 'sources': source_refs,
            'split_routes': [r for r in basis['rows'] if r['status'] == 'factory_quantities_needed'],
            'split_fingerprint': split_fp, 'history': events, 'snapshots': self.snapshots(month),
            'carry_reference': {k: carry_snapshot[k] for k in ('id','month','version')} if carry_snapshot else None,
            'previous_versions': prior_versions, 'carry_changed': carry_changed,
            'money_rule': '각 상세 공장 행의 수량 × 적용단가를 원 단위 사사오입 후 합산합니다. 천원 단위가 아닙니다.',
            'closing_total': str(sum((Decimal(r['closing_total'] or '0') for r in rows if r['status'] == 'ready'), Decimal(0))),
            'amount_total': str(sum((Decimal(r['amount'] or '0') for r in rows if r['status'] == 'ready'), Decimal(0)))}
        result['fingerprint'] = digest({'rule': RULE, 'sources': source_refs, 'rows': rows, 'issues': issues, 'carry': result['carry_reference']})
        result['no_hold_candidates'] = [r['part'] for r in rows if r['active'] and not r['opening_by_destination']
            and r['held'] is None and r['destinations_allowed'] and all(i['code']=='hold_required' for i in r['issues'])
            and (r['supplier']!='유미코아' or r['supplier_closing']==r['available'])]
        return result

    def confirm_no_holds(self, month, revision, fingerprint):
        before=self.store.get(month);Imports.revision(before,revision)
        view=self.preview(month)
        if view['fingerprint']!=fingerprint:raise WorkflowError('CALCULATION_CHANGED','일괄 확인 대상이 변경되었습니다.',409)
        rows=[r for r in view['rows'] if r['part'] in view['no_hold_candidates']]
        if not rows:raise WorkflowError('NO_CANDIDATES','원천 일치·전월 보류 없음 조건에 맞는 대상이 없습니다.')
        with self.store.connect(write=True) as conn:
            current=self.store.read(conn,month);Imports.revision(current,revision)
            for r in rows:
                lines=[{'destination':d,'new_hold':'0','released':'0','reason':'원천 일치·전월 보류 없는 품목의 보류 없음 일괄 확인',
                        'evidence':'통합 검토 화면에서 대상 목록 확인; 원천 '+r['fingerprints']['source']} for d in r['destinations_allowed']]
                payload=validate_lines({**r,'eligible':True,'destinations':r['destinations_allowed']},lines)
                conn.execute('INSERT INTO monthly_decision VALUES(?,?,?,?,?,?,?,?)',(uuid4().hex,current['id'],r['part'],'hold',current['revision']+1,r['fingerprints']['hold'],json.dumps(payload,ensure_ascii=False),now()))
                conn.execute('UPDATE draft SET revision=revision+1,updated_at=? WHERE id=?',(now(),current['id']))
                updated=self.store.read(conn,month);self.store.audit(conn,updated,'monthly_hold_batch',current);current=updated
        return {'draft':current,'count':len(rows)}

    def save(self, month, part, kind, revision, fingerprint, payload):
        if kind not in KINDS: raise WorkflowError('INVALID_EDIT', '수정 종류를 확인해 주세요.')
        before = self.store.get(month); Imports.revision(before, revision)
        view = self.preview(month)
        row = next((r for r in view['rows'] if r['part'] == part), None)
        fp = view['split_fingerprint'] if kind == 'splits' and part == '*' else row['fingerprints'].get(kind) if row else None
        if not fp or fp != fingerprint: raise WorkflowError('EDIT_STALE', '이 품목의 기준이 변경되었습니다. 최신 내용을 조회해 주세요.', 409)
        if payload is not None:
            payload = deepcopy(payload)
            if not isinstance(payload, dict) or not isinstance(payload.get('reason'), str) or not isinstance(payload.get('evidence'), str) or not payload['reason'].strip() or not payload['evidence'].strip():
                raise WorkflowError('EDIT_REASON', '변경 사유와 원본 행·전표 등의 근거를 적어 주세요.')
            if len(payload['reason']) > 1000 or len(payload['evidence']) > 2000: raise WorkflowError('EDIT_REASON', '사유·근거가 너무 깁니다.')
            if kind == 'carry': payload['quantity'] = quantity(payload.get('quantity'))
            elif kind == 'source':
                if payload.get('choice') not in ('supplier','erp','manual','previous'): raise WorkflowError('SOURCE_CHOICE', '적용 구성을 선택해 주세요.')
                if payload['choice'] == 'manual':
                    payload['prior'] = quantity(payload.get('prior')); payload['incoming'] = quantity(payload.get('incoming'), True)
                if payload['choice'] == 'erp' and (row['source']['ledger_prior'] is None or row['source']['erp_incoming'] is None): raise WorkflowError('SOURCE_MISSING', 'ERP·장부 원천이 없습니다.')
                if payload['choice'] == 'previous' and row['previous_final_held'] is None: raise WorkflowError('SOURCE_MISSING', '연결된 전월 확정본이 없습니다.')
            elif kind == 'hold':
                context = {**row, 'eligible': row['available'] is not None and Decimal(row['available']) >= 0 and not any(i['code'] in ('source_missing','source_difference','supplier_conflict','source_stale','carry_stale') for i in row['issues']), 'destinations': row['destinations_allowed']}
                if not isinstance(payload.get('lines'), list): raise WorkflowError('HOLD_LINES_REQUIRED', '마감처별 보류 내역이 필요합니다.')
                for line in payload['lines']:
                    if not isinstance(line,dict):raise WorkflowError('HOLD_LINES_REQUIRED','보류 내역의 형식을 확인해 주세요.')
                    line.setdefault('reason', payload['reason']); line.setdefault('evidence', payload['evidence'])
                    if not all(k in line for k in ('destination','new_hold','released')): raise WorkflowError('HOLD_LINES_REQUIRED', '보류·해소 수량을 모두 입력해 주세요.')
                    if any(not isinstance(line.get(k),str) for k in ('destination','new_hold','released','reason','evidence')):raise WorkflowError('HOLD_LINES_REQUIRED','마감처·수량·사유·근거를 문자 값으로 입력해 주세요.')
                payload.update(validate_lines(context, payload['lines']))
                lots=row['opening_lots']; supplied=payload.get('lot_releases',{})
                if not isinstance(supplied,dict) or set(supplied)-{p['lot_id'] for p in lots}:raise WorkflowError('HOLD_LOTS','전월 보류의 단가별 내역이 변경되었습니다.')
                releases={}
                for line in payload['lines']:
                    owned=[p for p in lots if p['destination']==line['destination']]
                    for lot in owned:
                        q=quantity(supplied.get(lot['lot_id'],line['released'] if len(owned)==1 else '0'))
                        if Decimal(q)>Decimal(lot['remaining']):raise WorkflowError('HOLD_LOTS','해소가 해당 단가 구분의 전월 보류를 넘습니다.')
                        releases[lot['lot_id']]=q
                    if owned and sum((Decimal(releases[p['lot_id']]) for p in owned),Decimal(0))!=Decimal(line['released']):raise WorkflowError('HOLD_LOTS','마감처의 해소 합계와 단가 구분별 해소 합계가 다릅니다.')
                payload['lot_releases']=releases
            elif kind == 'mapping':
                if not row['mapping_allowed']: raise WorkflowError('MAPPING_PROTECTED', '실제 입고 전용 경로는 수동 배분으로 대체할 수 없습니다.')
                self.validate_lines(payload, ('destination','plant','weight'))
                for x in payload['lines']:
                    x['weight'] = quantity(x['weight'])
                    if '글로비스' in x['destination']: raise WorkflowError('GLOVIS_PROTECTED', '글로비스는 제품 실제 입고와 BOM으로 연결해야 합니다.')
            elif kind == 'statement':
                if row['supplier']!='유미코아' or row['statement_difference'] in (None,'0') or payload.get('acknowledged') is not True:
                    raise WorkflowError('STATEMENT_REVIEW','유미코아 원문 마감과 적용 총량의 차이 및 사유를 확인해 주세요.')
            elif kind == 'quantities':
                self.validate_lines(payload, ('destination','plant','quantity'), nullable=('quantity',))
                known = {(p['destination'],p['plant']): p for p in row['plants']}
                for x in payload['lines']:
                    p = known.get((x['destination'],x['plant']))
                    if not p: raise WorkflowError('PLANT_CHANGED', '현재 계산에 없는 상세 공장입니다.')
                    if x['quantity'] in ('',None): x['quantity'] = None
                    else:
                        x['quantity'] = quantity(x['quantity'])
                        if p['kind'] == '실제 입고': raise WorkflowError('GLOVIS_PROTECTED', '글로비스 수량은 실제 입고 원본에서 수정해 주세요.')
            elif kind == 'prices':
                self.validate_lines(payload, ('destination','price','price_kind'))
                allowed = {p['destination'] for p in row['plants']} | {x['destination'] for x in row['hold_lines']}
                for x in payload['lines']:
                    if x['destination'] not in allowed: raise WorkflowError('PRICE_DESTINATION', '계산된 마감처를 선택해 주세요.')
                    if x['price_kind'] not in ('가단가','정단가'):raise WorkflowError('PRICE_KIND','가단가 또는 정단가를 선택해 주세요.')
                    try: p = Decimal(x['price'])
                    except (InvalidOperation, TypeError): raise WorkflowError('INVALID_PRICE', '단가를 숫자로 입력해 주세요.') from None
                    if not p.is_finite() or p < 0 or p > Decimal('1e12') or p.as_tuple().exponent < -6: raise WorkflowError('INVALID_PRICE', '단가 범위·소수 자릿수를 확인해 주세요.')
                    x['price'] = str(p)
            elif kind == 'splits':
                self.validate_lines(payload, ('route_id','quantity'))
                payload['lines'] = [{'kind':'공장수량','key':x['route_id'],'quantities':{'공장별납품수량':quantity(x['quantity'])},'reason':payload['reason'],'basis':payload['evidence']} for x in payload['lines']]
                apply_splits(deepcopy(Basis(self.store).preview(month)['rows']), payload['lines'])
        with self.store.connect(write=True) as conn:
            current = self.store.read(conn, month); Imports.revision(current, revision)
            event_id = uuid4().hex
            conn.execute('INSERT INTO monthly_decision VALUES(?,?,?,?,?,?,?,?)', (event_id,current['id'],part,kind,revision+1,fp,json.dumps(payload,ensure_ascii=False),now()))
            conn.execute('UPDATE draft SET revision=revision+1,updated_at=? WHERE id=?', (now(),current['id']))
            draft = self.store.read(conn,month); self.store.audit(conn,draft,'monthly_'+kind,current)
        return {'draft': draft, 'decision_id': event_id}

    @staticmethod
    def validate_lines(payload, fields, nullable=()):
        lines = payload.get('lines')
        if not isinstance(lines, list) or not 1 <= len(lines) <= 200: raise WorkflowError('EDIT_LINES', '수정할 행을 입력해 주세요.')
        seen = set()
        for x in lines:
            if not isinstance(x, dict) or any(k not in x or (k not in nullable and (not isinstance(x[k],str) or not x[k].strip() or len(x[k])>200)) for k in fields): raise WorkflowError('EDIT_LINES', '필수 항목을 모두 입력해 주세요.')
            identity = tuple(x[k] for k in fields if k in ('destination','plant','route_id'))
            if identity in seen: raise WorkflowError('DUPLICATE_EDIT', '같은 행을 중복 입력할 수 없습니다.')
            seen.add(identity)

    def finalize(self, month, revision, fingerprint, request_key):
        if not isinstance(request_key,str) or not re.fullmatch(r'[A-Za-z0-9_-]{8,100}', request_key): raise WorkflowError('INVALID_KEY','확정 요청 식별자를 확인해 주세요.')
        with self.store.connect() as conn:
            existing = conn.execute('SELECT id,month,revision,fingerprint FROM closing_snapshot WHERE request_key=?',(request_key,)).fetchone()
        if existing:
            if (existing['month'],existing['revision'],existing['fingerprint'])!=(month,revision,fingerprint): raise WorkflowError('REQUEST_CONFLICT','같은 확정 요청 식별자에 다른 내용이 전달되었습니다.',409)
            return self.snapshot(existing['id'])
        before = self.store.get(month); Imports.revision(before, revision)
        view = self.preview(month)
        if view['fingerprint'] != fingerprint: raise WorkflowError('CALCULATION_CHANGED','확정 전 계산 기준이 변경되었습니다.',409)
        if not view['ready']: raise WorkflowError('CLOSING_REVIEW_REQUIRED','미확인 수량·마감처·단가를 해결한 뒤 확정해 주세요.')
        with self.store.connect(write=True) as conn:
            existing=conn.execute('SELECT id,month,revision,fingerprint FROM closing_snapshot WHERE request_key=?',(request_key,)).fetchone()
            if existing:
                if (existing['month'],existing['revision'],existing['fingerprint'])!=(month,revision,fingerprint):raise WorkflowError('REQUEST_CONFLICT','같은 확정 요청 식별자에 다른 내용이 전달되었습니다.',409)
                return self.snapshot(existing['id'])
            current = self.store.read(conn,month); Imports.revision(current,revision)
            version = conn.execute('SELECT COALESCE(MAX(version),0)+1 FROM closing_snapshot WHERE month=?',(month,)).fetchone()[0]
            snapshot_id = uuid4().hex
            # All normalized source records are frozen along with originals' hashes.
            evidence = Imports(self.store).effective_sources(month)
            view['frozen_evidence'] = evidence
            from backend.application.reporting import freeze_report_context
            view['report_context'] = freeze_report_context(self.store, conn, month, evidence,
                as_of=now(), carry_reference=view.get('carry_reference'))
            conn.execute('INSERT INTO closing_snapshot VALUES(?,?,?,?,?,?,?,?,?)',(snapshot_id,month,version,current['id'],revision,request_key,fingerprint,json.dumps(view,ensure_ascii=False,default=str),now()))
            conn.execute('INSERT INTO draft_lock VALUES(?,?)',(current['id'],snapshot_id))
            conn.execute('UPDATE draft SET revision=revision+1,updated_at=? WHERE id=?',(now(),current['id']))
            self.store.audit(conn,self.store.read(conn,month),'closing_finalized',current)
        return self.snapshot(snapshot_id)

    def reopen(self, month, revision, reason):
        if not reason.strip(): raise WorkflowError('REOPEN_REASON','재작업 사유를 적어 주세요.')
        with self.store.connect(write=True) as conn:
            before = self.store.read(conn,month)
            if before['revision'] != revision or not before['finalized']: raise WorkflowError('REVISION_CONFLICT','최신 확정 상태를 조회해 주세요.',409)
            conn.execute('DELETE FROM draft_lock WHERE draft_id=?',(before['id'],))
            conn.execute('UPDATE draft SET revision=revision+1,updated_at=? WHERE id=?',(now(),before['id']))
            draft = self.store.read(conn,month); self.store.audit(conn,{**draft,'reopen_reason':reason},'closing_reopened',before)
        return draft

    def link_carry(self, month, revision, snapshot_id):
        snapshot = self.snapshot(snapshot_id)
        if snapshot['month'] != previous_month(month): raise WorkflowError('CARRY_MONTH','바로 전월의 확정본만 연결할 수 있습니다.')
        with self.store.connect(write=True) as conn:
            before = self.store.read(conn,month); Imports.revision(before,revision)
            conn.execute('INSERT INTO carry_reference VALUES(?,?) ON CONFLICT(draft_id) DO UPDATE SET snapshot_id=excluded.snapshot_id',(before['id'],snapshot_id))
            conn.execute('UPDATE draft SET revision=revision+1,updated_at=? WHERE id=?',(now(),before['id']))
            draft = self.store.read(conn,month); self.store.audit(conn,{**draft,'carry_snapshot':snapshot_id},'carry_linked',before)
        return draft
