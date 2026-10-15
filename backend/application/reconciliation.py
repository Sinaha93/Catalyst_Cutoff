"""Compare independent monthly source quantities without rewriting differences."""
from collections import Counter, defaultdict
from decimal import Decimal
import hashlib
import json

from backend.application.imports import Imports
from backend.application.basis import normalized, source_ref
from backend.domain.errors import WorkflowError
from backend.application.dependencies import digest, record_content, parser_rule

RULE_VERSION='source-reconciliation-2'
ROLES=('heesung_shipments','heesung_carryover','umicore_statement','erp_receipts','comparison_report')


def part_fingerprint(sources, row):
    required = {'erp_receipts', 'comparison_report'}
    if row['supplier'] == '희성': required.update(('heesung_shipments', 'heesung_carryover'))
    elif row['supplier'] == '유미코아': required.add('umicore_statement')
    scoped = {}
    for role in ROLES:
        batch = sources.get(role)
        records = [r for r in batch['records'] if r['part'] == row['part']] if batch else []
        # An unrelated supplier's replacement cannot affect this part. A
        # conflicting record in that source, however, is a relevant dependency.
        if role not in required and not records: continue
        scoped[role] = None if not batch else {'period': batch['source_period'], 'parser': parser_rule(batch),
            'records': sorted([record_content(batch, r) for r in records], key=digest)}
    return digest({'rule': RULE_VERSION, 'sources': scoped})


def reconcile(sources):
    grouped={}
    for role,batch in sources.items():
        bypart=defaultdict(list)
        for r in batch['records']:
            if role=='erp_receipts' and not normalized(r)['included']:continue
            bypart[r['part']].append(r)
        grouped[role]=bypart
    parts=sorted(set().union(*(set(v) for v in grouped.values())))
    out=[]
    for part in parts:
        def records(role):return grouped.get(role,{}).get(part,[])
        def total(role,field=None):
            if role not in sources:return None
            rows=records(role)
            # Explicitly adopted full-month source with no transaction: zero,
            # with the absence and source identity retained below.
            return sum((Decimal(normalized(r)[field] if field else r['quantity']) for r in rows),Decimal(0))
        hs=bool(records('heesung_shipments') or records('heesung_carryover'));umi=bool(records('umicore_statement'))
        row={'part':part,'supplier':'희성' if hs else '유미코아' if umi else None,'status':'matched','issues':[],
             'supplier_prior':None,'supplier_incoming':None,'supplier_available':None,'ledger_prior':None,'erp_incoming':None,'ledger_available':None,
             'prior_difference':None,'incoming_difference':None,'total_difference':None,'historical_held':None,'hold_details':[], 'suggested_pool':None,
             'evidence':{role:[source_ref(batch,r) for r in records(role)] for role,batch in sources.items()},
             'absent_from':[role for role in sources if not records(role)]}
        out.append(row)
        def issue(code,message):row['issues'].append({'code':code,'message':message})
        if hs and umi:issue('supplier_conflict','두 촉매사에 같은 품번이 있습니다. 합산하지 않습니다.');row['status']='supplier_conflict';continue
        prior=incoming=None
        if hs:prior=total('heesung_carryover');incoming=total('heesung_shipments')
        elif umi:
            if len(records('umicore_statement'))!=1:issue('supplier_conflict','유미코아 품번 행이 중복됩니다.')
            else:
                metrics=normalized(records('umicore_statement')[0])['metrics'];prior=Decimal(metrics['전월 적송재고']);incoming=Decimal(metrics['납품 수량'])
        else:issue('supplier_missing','촉매사 출하·이월 자료에 없는 품번입니다. ERP나 보고서만으로 촉매사를 정하지 않습니다.')
        lp=total('comparison_report','prior');erp=total('erp_receipts');held=total('comparison_report','held')
        available=prior+incoming if prior is not None and incoming is not None else None
        ledger_available=lp+erp if lp is not None and erp is not None else None
        for key,value in [('supplier_prior',prior),('supplier_incoming',incoming),('supplier_available',available),('ledger_prior',lp),('erp_incoming',erp),('ledger_available',ledger_available),('historical_held',held)]:row[key]=str(value) if value is not None else None
        for key,a,b in [('prior_difference',prior,lp),('incoming_difference',incoming,erp),('total_difference',available,ledger_available)]:row[key]=str(a-b) if a is not None and b is not None else None
        row['hold_details']=[{**normalized(r),'evidence':source_ref(sources['comparison_report'],r)} for r in records('comparison_report') if Decimal(normalized(r)['held'])>0]
        if any(v is None for v in (prior,incoming,lp,erp)):issue('source_missing','전월 적송재고·출하·ERP 입고·비교 보고서 중 필요한 채택 자료가 없습니다.')
        if available is not None and available<0:issue('negative_available','촉매사 원천 총량이 음수입니다. 반품·정정 근거를 확인해야 합니다.')
        if row['total_difference'] is not None and Decimal(row['total_difference'])!=0:issue('total_difference','촉매사 총량과 ERP·이월 장부 총량이 다릅니다.')
        elif row['prior_difference'] is not None and (Decimal(row['prior_difference'])!=0 or Decimal(row['incoming_difference'] or '0')!=0):issue('composition_difference','총량은 같지만 전월 이월·당월 입고 구성이 다릅니다. 서로 다른 기준을 섞지 않습니다.')
        row['status']=row['issues'][0]['code'] if row['issues'] else 'matched'
        # Only propose source composition, never infer hold=0 or use historical
        # final closing/hold to force reproduction of last month's outcome.
        if row['status']=='matched':row['suggested_pool']={'전월이월':str(prior),'당월입고':str(incoming),'조정':'0','미마감보류':None}
    return {'rows':out,'status_counts':dict(Counter(r['status'] for r in out)),
            'notice':'촉매사 원천과 ERP·이월 장부를 대조합니다. 총량 일치와 이월·입고 구성 일치를 구분하며, 기존 보고서 미마감은 비교값입니다. 과거 결과를 빼서 새 마감 수량을 맞추지 않습니다.'}


class Reconciliation:
    def __init__(self,store):self.store=store

    def preview(self,month):
        before=self.store.get(month);imports=Imports(self.store);sources={}
        for batch in imports.list(month):
            if batch['selected'] and batch['role'] in ROLES:
                imports.original(month,batch['id']);b=imports.detail(month,batch['id'])
                if b['status']!='ready':raise WorkflowError('SOURCE_NOT_READY','원천 대조 자료의 읽기 검산을 확인해 주세요.')
                sources[b['role']]=b
        result=reconcile(sources)
        if self.store.get(month)['revision']!=before['revision']:raise WorkflowError('REVISION_CONFLICT','대조 중 원본이 변경되었습니다. 다시 조회해 주세요.',409)
        refs={role:{k:b[k] for k in ('id','filename','sha256')} for role,b in sources.items()}
        result.update(month=month,revision=before['revision'],sources=refs,missing_roles=[r for r in ROLES if r not in sources],rule_version=RULE_VERSION,
                      input_fingerprint=hashlib.sha256(json.dumps({'sources':refs,'rule':RULE_VERSION},sort_keys=True).encode()).hexdigest())
        result['part_fingerprints'] = {row['part']: part_fingerprint(sources, row) for row in result['rows']}
        return result
