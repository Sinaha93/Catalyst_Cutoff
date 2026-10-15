"""Check saved business report cells against the immutable closing snapshot.

Compare each item/destination, not only grand totals: equal and opposite
mistakes in two destinations must still prevent publishing an export.
"""
from collections import defaultdict
from decimal import Decimal, InvalidOperation

from backend.domain.errors import WorkflowError


ZERO = Decimal(0)


def number(value):
    if value is None:
        return None
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise WorkflowError('EXPORT_BALANCE', '출력표에 올바르지 않은 숫자가 있습니다.') from None
    if not result.is_finite():
        raise WorkflowError('EXPORT_BALANCE', '출력표에 올바르지 않은 숫자가 있습니다.')
    return result


def validate_business_export(book, data, model):
    checked = []

    def require(name):
        if name not in book.sheetnames:
            raise WorkflowError('EXPORT_VALIDATION', f'{name} 시트가 출력에서 빠졌습니다.')
        return book[name]

    def same(name, expected, found):
        if expected != found:
            keys = set(expected) | set(found)
            key = next(k for k in sorted(keys, key=str) if expected.get(k) != found.get(k))
            label = ' / '.join(str(x) for x in key) if isinstance(key, tuple) else str(key)
            raise WorkflowError('EXPORT_BALANCE', f'{name}: {label}의 출력 수량·금액이 확정값과 다릅니다.')
        checked.append(name)

    def group(records):
        result = {}
        for key, values in records:
            values = tuple(number(v) for v in values)
            if any(v is None for v in values):
                raise WorkflowError('EXPORT_BALANCE', '확정 수량·금액에 빈 값이 있습니다.')
            previous = result.get(key, (ZERO,) * len(values))
            result[key] = tuple(a+b for a,b in zip(previous,values))
        return result

    plants = [(r,p) for r in data['rows'] for p in r['plants']]
    expected = group(((r['supplier'],r['part'],p['destination']), (p['quantity'],p['amount'])) for r,p in plants)
    found = group(((r[0],r[1],r[2]),(r[5],r[6])) for r in require('ERP 거래처별 검토').iter_rows(min_row=2,values_only=True) if r[1])
    same('ERP 거래처별 검토',expected,found)
    same('확정 합계', {'합계':(number(data['closing_total']),number(data['amount_total']))},
        {'합계':tuple(sum((v[i] for v in expected.values()),ZERO) for i in (0,1))})

    for destination in model['destinations']:
        name=model['destination_sheets'][destination]; s=require(name)
        expected=group(((r['supplier'],r['part']),(p['quantity'],p['amount'])) for r,p in plants
                       if p['destination']==destination and number(p['quantity'])!=ZERO)
        found=group(((r[5],r[1]),(r[3],r[4])) for r in s.iter_rows(min_row=7,max_col=8,values_only=True) if isinstance(r[0],int))
        same(name,expected,found)
        totals=[(number(r[3]),number(r[4])) for r in s.iter_rows(min_row=7,max_col=8,values_only=True) if r[0]=='합계']
        expected_total=tuple(sum((v[i] for v in expected.values()),ZERO) for i in (0,1))
        if totals!=[expected_total]:
            raise WorkflowError('EXPORT_BALANCE',f'{name}: 계산서 합계가 품목별 합계와 다릅니다.')

    expected=group(((r['supplier'],r['part'],p['destination'],p['plant']),
                    (p['automatic_quantity'],p['quantity'],p['amount'])) for r,p in plants)
    found=group(((r[0],r[1],r[2],r[3]),(r[4],r[5],r[8]))
                for r in require('공장별 마감').iter_rows(min_row=7,values_only=True) if r[1])
    same('공장별 마감',expected,found)

    for supplier,name in [('희성','희성 마감가공'),('유미코아','유미코아 마감검토')]:
        expected=group(((r['part'],p['destination'],p['plant']),(p['quantity'],p['amount']))
                       for r,p in plants if r['supplier']==supplier)
        found=group(((r[0],r[2],r[1]),(r[4],r[7]))
                    for r in require(name).iter_rows(min_row=2,values_only=True) if r[0] and r[1]!='마감 없음')
        same(name,expected,found)

    pending=[(r,p) for r in data['rows'] for p in r['pending']]
    def pending_values(p):
        return tuple(p[k] or '0' for k in ('opening','new_hold','released','remaining','amount'))
    expected=group(((r['supplier'],r['part'],p['destination']),pending_values(p)) for r,p in pending)
    found=group(((r[0],r[1],r[2]),(*r[3:7],r[9]))
                for r in require('미정산 이월').iter_rows(min_row=2,values_only=True) if r[1])
    same('미정산 이월',expected,found)
    nonzero=[(r,p) for r,p in pending if any(number(p[k]) for k in ('opening','new_hold','released','remaining'))]
    expected=group(((r['supplier'],r['part'],p['destination']),pending_values(p)) for r,p in nonzero)
    found=group(((r[2],r[1],r[0]),r[5:10])
                for r in require('미마감 내역').iter_rows(min_row=7,values_only=True) if r[1])
    same('미마감 내역',expected,found)
    expected_total=tuple(sum((v[i] for v in expected.values()),ZERO) for i in range(5))
    totals=[tuple(number(x) for x in row[5:10]) for row in require('미마감 내역').iter_rows(min_row=7,values_only=True) if row[0]=='합계']
    if totals!=[expected_total]:
        raise WorkflowError('EXPORT_BALANCE','미마감 내역: 합계가 품목별 합계와 다릅니다.')

    expected={(r['supplier'],r['part']):tuple(number(r[k]) for k in
        ('original_prior','prior','incoming','closing_total','held','balance')) for r in data['rows']}
    found={(r[0],r[1]):tuple(number(v) for v in r[2:8]) for r in require('수량 검산').iter_rows(min_row=2,values_only=True) if r[1]}
    same('수량 검산',expected,found)

    s=require('희성 마감자료'); headings=[c.value for c in s[6]]
    start=4; stop=headings.index('마감 합계'); factory_names=headings[start:stop]
    expected={}
    for row in data['rows']:
        if row['supplier']!='희성' or not (row['active'] or row['plants']):continue
        counts=defaultdict(lambda:ZERO)
        for p in row['plants']:
            destination=p['destination']
            if destination=='현대 위아':key=p['plant']
            elif destination=='현대 울산':key='울산 CKD' if 'CKD' in p['plant'].upper() else '울산'
            else:key={'현대 아산':'아산','현대 글로비스':'글로비스','세종공업':'세종','현대 모비스':'모비스'}.get(destination,destination)
            if key not in factory_names:raise WorkflowError('EXPORT_BALANCE',f'희성 마감자료: {key} 공장 열이 빠졌습니다.')
            counts[key]+=number(p['quantity'])
        expected[row['part']]=(number(row['prior']),number(row['incoming']),*[counts[k] for k in factory_names],
            *[number(row[k]) for k in ('closing_total','available','held','balance')])
    found={r[0]:tuple(number(v) for v in r[2:stop+4]) for r in s.iter_rows(min_row=7,values_only=True) if r[0] and r[0]!='합계'}
    same('희성 마감자료',expected,found)
    totals=[tuple(number(v) for v in r[2:stop+4]) for r in s.iter_rows(min_row=7,values_only=True) if r[0]=='합계']
    expected_total=tuple(sum((v[i] or ZERO for v in expected.values()),ZERO) for i in range(stop+2))
    if totals!=[expected_total]:raise WorkflowError('EXPORT_BALANCE','희성 마감자료: 합계가 품목별 합계와 다릅니다.')

    expected={}
    for d in model['destinations']:
        ps=[p for _,p in plants if p['destination']==d]; holds=[p for _,p in pending if p['destination']==d]
        q=sum((number(p['quantity']) for p in ps),ZERO); amount=sum((number(p['amount']) for p in ps),ZERO)
        opening=sum((number(p['opening']) for p in holds),ZERO); held=sum((number(p['remaining']) for p in holds),ZERO)
        held_amount=sum((number(p['amount']) or ZERO for p in holds),ZERO); opening_amount=model['opening_amounts'][d]
        expected[d]=(opening,opening_amount,q+held-opening,
            amount+held_amount-opening_amount if opening_amount is not None else None,q,amount,held,held_amount)
    found={r[1]:tuple(None if v=='미확인' else number(v) for v in r[2:10])
           for r in require('종합').iter_rows(min_row=3,values_only=True) if isinstance(r[0],int)}
    same('종합',expected,found)
    expected_total=tuple(sum((v[i] for v in expected.values()),ZERO) if all(v[i] is not None for v in expected.values()) else None for i in range(8))
    totals=[tuple(None if v=='미확인' else number(v) for v in r[2:10]) for r in require('종합').iter_rows(min_row=3,values_only=True) if r[0]=='TOTAL']
    if totals!=[expected_total]:raise WorkflowError('EXPORT_BALANCE','종합: TOTAL이 거래처별 합계와 다릅니다.')
    return checked
