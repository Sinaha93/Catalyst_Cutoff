"""Append-only monthly hold decisions bound to their original source versions."""
from collections import defaultdict
from decimal import Decimal
import hashlib
import json
import re
from uuid import uuid4

from backend.adapters.storage import now
from backend.application.basis import Basis, normalized, source_ref
from backend.application.imports import Imports
from backend.application.reconciliation import Reconciliation
from backend.domain.errors import WorkflowError

RULE_VERSION='monthly-hold-1'


def validate_lines(context, lines):
    if not context['eligible']:raise WorkflowError('HOLD_SOURCE_REVIEW','원천 수량 차이를 먼저 해결해야 합니다. 총량을 임의로 맞추는 보류를 저장하지 않습니다.')
    if not lines or len(lines)>100:raise WorkflowError('HOLD_LINES_REQUIRED','보류 처리 내역을 입력해 주세요. 보류 없음도 수량 0과 사유를 남깁니다.')
    expected=context['opening_by_destination'];seen=set();result=[];total=0;new_total=0
    for line in lines:
        destination=line['destination'].strip()
        if destination not in context['destinations'] or destination in seen:
            raise WorkflowError('HOLD_DESTINATION','등록된 마감처를 선택하고 같은 마감처를 중복 입력하지 말아 주세요.')
        seen.add(destination)
        values={}
        for key in ('new_hold','released'):
            value=line[key]
            if not isinstance(value,str) or not re.fullmatch(r'\d{1,12}',value):raise WorkflowError('HOLD_QUANTITY','신규 보류·해소 수량은 0 이상의 정수로 입력해 주세요. 공란은 0이 아닙니다.')
            values[key]=int(value)
        opening=int(expected.get(destination,'0'))
        if values['released']>opening:raise WorkflowError('HOLD_RELEASE_EXCEEDS','해소 수량은 해당 마감처의 전월 이월 보류를 넘을 수 없습니다.')
        reason=line['reason'].strip();evidence=line['evidence'].strip()
        if not reason or not evidence or len(reason)>1000 or len(evidence)>2000:
            raise WorkflowError('HOLD_EVIDENCE_REQUIRED','처리 사유와 파일·행·전표 등 근거를 입력해 주세요.')
        remaining=opening+values['new_hold']-values['released'];total+=remaining;new_total+=values['new_hold']
        action='신규 보류' if not opening and values['new_hold'] else '보류 없음' if not opening else '전부 해소' if values['released']==opening else '일부 해소' if values['released'] else '보류 계속'
        if opening and values['new_hold']:action+=' + 신규 보류'
        result.append({'destination':destination,'opening':str(opening),'new_hold':str(values['new_hold']),'released':str(values['released']),'remaining':str(remaining),'action':action,'reason':reason,'evidence':evidence})
    if set(expected)-seen:raise WorkflowError('HOLD_OPENING_MISSING','전월 이월 보류가 있는 모든 마감처의 계속·해소 여부를 입력해 주세요.')
    if Decimal(new_total)>max(Decimal(context['incoming']),Decimal(0)):
        raise WorkflowError('HOLD_NEW_EXCEEDS','신규 보류 합계가 당월 입고 수량을 넘습니다.')
    if Decimal(total)>Decimal(context['available']):raise WorkflowError('HOLD_EXCEEDS_AVAILABLE','미마감 보류 합계가 촉매 가용 총량을 넘습니다.')
    return {'lines':result,'held':str(total)}


class Holds:
    def __init__(self,store):self.store=store

    def history(self,month):
        with self.store.connect() as conn:
            draft=self.store.read(conn,month)
            return [{**dict(r),'payload':json.loads(r['payload_json'])} for r in conn.execute('SELECT * FROM hold_decision WHERE draft_id=? ORDER BY revision DESC',(draft['id'],))]

    def preview(self,month):
        reconciliation=Reconciliation(self.store).preview(month);basis=Basis(self.store).preview(month)
        if reconciliation['revision']!=basis['revision']:raise WorkflowError('REVISION_CONFLICT','조회 중 자료가 변경되었습니다.',409)
        fingerprint=hashlib.sha256(json.dumps({'source':reconciliation['input_fingerprint'],'basis':basis['input_fingerprint'],'rule':RULE_VERSION},sort_keys=True).encode()).hexdigest()
        destinations=defaultdict(set)
        for route in basis['rows']:
            for c in route['components']:
                if c.get('destination'):destinations[c['part']].add(c['destination'])
        imports=Imports(self.store);opening=defaultdict(lambda:defaultdict(Decimal));opening_refs=defaultdict(list)
        ref=reconciliation['sources'].get('comparison_report')
        if ref:
            for r in imports.detail(month,ref['id'])['records']:
                n=normalized(r);destinations[r['part']].add(n['destination'])
                if Decimal(n['prior'])>0:
                    opening[r['part']][n['destination']]+=Decimal(n['prior'])
                    opening_refs[r['part']].append({**source_ref(ref,r),'prior':n['prior'],'destination':n['destination']})
        events=self.history(month);latest={}
        for event in events:latest.setdefault(event['part'],event)
        rows=[]
        for r in reconciliation['rows']:
            part=r['part'];event=latest.get(part)
            rows.append({'part':part,'supplier':r['supplier'],'source_status':r['status'],'available':r['supplier_available'],'incoming':r['supplier_incoming'],
                         'prior':r['supplier_prior'],'opening_by_destination':{d:str(q) for d,q in opening[part].items()},'opening_evidence':opening_refs[part],
                         'destinations':sorted(destinations[part]),'historical_held':r['historical_held'],
                         'eligible':r['status']=='matched' and bool(destinations[part]) and r['supplier_available'] is not None and Decimal(r['supplier_available'])>=0,
                         'decision':event,'decision_status':'none' if not event else 'current' if event['fingerprint']==fingerprint else 'stale'})
        if self.store.get(month)['revision']!=basis['revision']:raise WorkflowError('REVISION_CONFLICT','조회 중 자료가 변경되었습니다.',409)
        return {'month':month,'revision':basis['revision'],'input_fingerprint':fingerprint,'rows':rows,'history':events,
                'source_fingerprint':reconciliation['input_fingerprint'],'basis_fingerprint':basis['input_fingerprint'],
                'notice':'전월 보류는 장부의 전월 이월에서 연결합니다. 기존 보고서의 당월 미마감은 비교값입니다. 저장한 내역은 새 버전으로 남으며 원본 기준이 바뀌면 재확인이 필요합니다.'}

    def save(self,month,part,expected_revision,fingerprint,lines):
        before=self.store.get(month);Imports.revision(before,expected_revision)
        preview=self.preview(month)
        if fingerprint!=preview['input_fingerprint']:raise WorkflowError('HOLD_BASIS_CHANGED','원본 기준이 변경되었습니다. 최신 보류 기준을 조회한 뒤 확인해 주세요.',409)
        context=next((r for r in preview['rows'] if r['part']==part),None)
        if context is None:raise WorkflowError('HOLD_PART_UNKNOWN','현재 원천에 없는 품번입니다.')
        payload=validate_lines(context,lines)
        payload.update(context={k:context[k] for k in ('part','supplier','prior','incoming','available','opening_by_destination','opening_evidence','historical_held')},
                       source_fingerprint=preview['source_fingerprint'],basis_fingerprint=preview['basis_fingerprint'],
                       supersedes=context['decision']['id'] if context['decision'] else None)
        with self.store.connect(write=True) as conn:
            current=self.store.read(conn,month);Imports.revision(current,expected_revision)
            event_id=uuid4().hex;stamp=now()
            conn.execute('INSERT INTO hold_decision VALUES(?,?,?,?,?,?,?)',(event_id,current['id'],part,current['revision']+1,fingerprint,json.dumps(payload,ensure_ascii=False),stamp))
            conn.execute('UPDATE draft SET revision=revision+1,updated_at=? WHERE id=?',(stamp,current['id']))
            draft=self.store.read(conn,month);self.store.audit(conn,draft,'hold_saved',current)
        return {'draft':draft,'decision_id':event_id,'held':payload['held']}

    def pools(self,month,basis):
        # Do not demand new source types for legacy W4.1 workspaces with no holds.
        if not self.history(month):return [],{},None
        preview=self.preview(month);parts={c['part'] for r in basis['rows'] if r['supplier'] in ('희성','희성촉매') for c in r['components']}
        pools=[];states={}
        for r in preview['rows']:
            if not r['decision'] or r['part'] not in parts:continue
            states[r['part']]=r['decision_status']
            if r['decision_status']!='current' or not r['eligible']:continue
            event=r['decision'];payload=event['payload']
            pools.append({'kind':'촉매총량','key':r['part'],'quantities':{'전월이월':r['prior'],'당월입고':r['incoming'],'조정':'0','미마감보류':payload['held']},
                          'reason':'일치한 원천 + 월별 보류 처리','basis':'; '.join(x['reason']+' / '+x['evidence'] for x in payload['lines']),
                          'hold_decision':{'id':event['id'],'revision':event['revision'],'lines':payload['lines']},
                          'evidence':{'filename':'월별 보류 처리 이력','sheet':month,'row_number':event['revision']}})
        return pools,states,preview['input_fingerprint']
