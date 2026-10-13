"""Resolve unit prices independently of plan values and settlement allocation."""
from collections import defaultdict
from decimal import Decimal
import hashlib
import json

from backend.application.imports import Imports
from backend.application.basis import normalized, source_ref
from backend.domain.errors import WorkflowError

RULE_VERSION='pricing-preview-1'


def resolve_price(catalyst,destination,prices,policies):
    candidates=prices.get(catalyst,[])
    matches=[r for r in policies if r['part']==catalyst and normalized(r)['destination']==destination]
    if not matches:matches=[r for r in policies if r['part']==catalyst and normalized(r)['destination']=='전체']
    result={'erp_candidates':sorted({format(Decimal(normalized(r)['price']).normalize(),'f') for r in candidates if normalized(r)['price'] is not None},key=Decimal),'applied_price':None,'price_kind':None,'status':'price_missing','policy_evidence':None,'reason':None}
    if len(matches)>1:result['status']='policy_conflict'
    elif matches:
        n=normalized(matches[0]);result.update(applied_price=n['price'],price_kind=n['price_kind'],status='policy_applied',policy_evidence=matches[0],reason=n['reason'],basis=n['basis'])
    elif len(result['erp_candidates'])==1:result.update(applied_price=result['erp_candidates'][0],price_kind='ERP 등록 단가',status='erp_price')
    elif len(result['erp_candidates'])>1:result['status']='price_conflict'
    return result


class Pricing:
    def __init__(self,store):self.store=store

    def preview(self,month):
        before=self.store.get(month);imports=Imports(self.store)
        chosen={b['role']:b for b in imports.list(month) if b['selected']}
        if any(r not in chosen for r in ('price_master','plan_master')):
            raise WorkflowError('PRICE_PLAN_REQUIRED','ERP 단가와 월계획 원본을 등록하고 이번 달 자료로 채택해 주세요.')
        sources={}
        for role in ('price_master','plan_master','price_policy'):
            if role in chosen:
                imports.original(month,chosen[role]['id']);sources[role]=imports.detail(month,chosen[role]['id'])
                if sources[role]['status']!='ready':raise WorkflowError('SOURCE_NOT_READY','채택 단가·계획의 검산 상태를 확인해 주세요.')
        prices=defaultdict(list)
        for r in sources['price_master']['records']:prices[r['part']].append(r)
        policies=sources.get('price_policy',{}).get('records',[])
        rows=[];totals=defaultdict(lambda:{'quantity':Decimal(0),'amount':Decimal(0),'amount_complete':True})
        for r in sources['plan_master']['records']:
            n=normalized(r)
            if n['view']!='destination':continue
            resolved=resolve_price(r['part'],n['destination'],prices,policies)
            if resolved['policy_evidence']:
                resolved['policy_evidence']=source_ref(sources['price_policy'],resolved['policy_evidence'])
            rows.append({'part':r['part'],'destination':n['destination'],'supplier':n['supplier'],'plan_quantity':r['quantity'],'plan_price':n['plan_price'],'plan_amount':n['plan_amount'],**resolved,
                         'plan_evidence':source_ref(sources['plan_master'],r),'erp_evidence':[source_ref(sources['price_master'],x) for x in prices.get(r['part'],[])]})
            t=totals[n['destination']];t['quantity']+=Decimal(r['quantity'])
            if n['plan_amount'] is None:t['amount_complete']=False
            else:t['amount']+=Decimal(n['plan_amount'])
        if self.store.get(month)['revision']!=before['revision']:raise WorkflowError('REVISION_CONFLICT','조회 중 자료가 변경됐습니다. 다시 검토해 주세요.',409)
        refs={role:{'id':b['id'],'filename':b['filename'],'sha256':b['sha256']} for role,b in sources.items()}
        return {'month':month,'revision':before['revision'],'rule_version':RULE_VERSION,'sources':refs,
                'input_fingerprint':hashlib.sha256(json.dumps({'sources':refs,'rule_version':RULE_VERSION},sort_keys=True).encode()).hexdigest(),
                'rows':rows,'destination_totals':{d:{'quantity':str(v['quantity']),'amount':str(v['amount']) if v['amount_complete'] else None} for d,v in totals.items()},
                'quantity_total':str(sum((v['quantity'] for v in totals.values()),Decimal(0))),
                'amount_total':str(sum((v['amount'] for v in totals.values()),Decimal(0))) if all(v['amount_complete'] for v in totals.values()) else None,
                'price_conflicts':sources['price_master']['result']['summary']['conflict_parts'],
                'policy_rows':[{'part':r['part'],**normalized(r),'evidence':source_ref(sources['price_policy'],r)} for r in policies],
                'notice':'계획 금액은 계획 원본 단가로 유지합니다. 적용 단가는 실제 마감 계산용 기준이며 계획을 덮어쓰지 않습니다. 단가에서 마감처를 추정하지 않습니다.'}
