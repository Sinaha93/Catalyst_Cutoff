import {useEffect, useState} from 'react';
import {api, upload, type Draft} from './api';
import {PdfReview} from './PdfReview';

export type Source = {id:string; filename:string; created_at:string; role:string; source_period:string; selected:number; ever_selected?:number; status:string;
  result:{summary:{row_count?:number;part_count?:number;quantity_total?:string;printed_total?:string;period_confirmed?:boolean;quantity_label?:string;notices?:string[]};issues:{code:string;location:string;message:string}[]};
  records?:{ordinal:number;sheet:string;row_number:number;part:string;quantity:string|null;evidence:Record<string,{label?:string;value?:unknown;formula?:string|null;peer_quantity?:string;reviewed?:boolean}>}[]};
const labels:Record<string,string>={heesung_shipments:'희성 출하 원본',heesung_carryover:'희성 전월 적송재고 PDF',erp_receipts:'ERP 촉매 입고',product_stock:'제품 창고 수불',semi_stock:'반제품 창고 수불',umicore_statement:'유미코아 납품 Summary',glovis_receipts:'글로비스 실제 입고',bom_master:'BOM 기준',route_master:'통합 경로 기준',price_master:'ERP 단가',price_policy:'월별 적용 단가',plan_master:'월계획',allocation_inputs:'배분 수량 근거',comparison_report:'기존 보고서 미정산 비교'};
const label=(role:string)=>labels[role]??role;
const status=(s:Source)=>s.selected?'이번 달 사용':s.status==='ready'?'읽기 검산 완료':'확인 필요';
function previousMonth(month:string){const [y,m]=month.split('-').map(Number);return `${m===1?y-1:y}-${String(m===1?12:m-1).padStart(2,'0')}`}

export function Sources({draft,disabled,begin,end,onDirty}:{onDirty:(dirty:boolean)=>void;draft:Draft;disabled:boolean;begin:()=>boolean;end:(d?:Draft)=>void}) {
  const [sources,setSources]=useState<Source[]>([]),[selected,setSelected]=useState<Source>();
  const [role,setRole]=useState('heesung_shipments'),[file,setFile]=useState<File>();
  const [error,setError]=useState(''),[message,setMessage]=useState(''),[loading,setLoading]=useState(false);
  const [reviewDirty,setReviewDirty]=useState(false);
  const [periodConfirmed,setPeriodConfirmed]=useState(false);
  const [query,setQuery]=useState('');
  useEffect(()=>setQuery(''),[selected?.id]);
  const needsPeriod=['erp_receipts','product_stock','semi_stock','umicore_statement','glovis_receipts','bom_master','route_master','price_master','price_policy','plan_master','allocation_inputs','comparison_report'].includes(role);
  const otherDisabled=disabled||reviewDirty;
  const period=role==='heesung_carryover'?previousMonth(draft.month):draft.month;
  async function refresh(){setLoading(true);setError('');try{setSources(await api<Source[]>(`/months/${draft.month}/sources`))}catch(e){setError((e as Error).message)}finally{setLoading(false)}}
  useEffect(()=>{let active=true;setLoading(true);api<Source[]>(`/months/${draft.month}/sources`).then(s=>{if(active)setSources(s)}).catch(e=>{if(active)setError(e.message)}).finally(()=>{if(active)setLoading(false)});return()=>{active=false}},[draft.month,draft.revision]);
  async function register(){
    if(!file||reviewDirty||!begin())return;setError('');setMessage('');let updated:Draft|undefined;
    try{
      const params=new URLSearchParams({role,source_period:period,filename:file.name,expected_revision:String(draft.revision),period_confirmed:String(periodConfirmed)});
      const r=await upload<{draft:Draft;batch:Source;duplicate:boolean}>(`/months/${draft.month}/sources?${params}`,file);
      updated=r.draft;setSelected(r.batch);setMessage(r.duplicate?'같은 파일이 이미 등록되어 있습니다. 중복 추가하지 않았습니다.':'원본을 보관했습니다. 읽기 결과를 확인한 뒤 이번 달 자료로 선택해 주세요.');
      await refresh();
    }catch(e){setError((e as Error).message)}finally{end(updated)}
  }
  async function inspect(source:Source){if(reviewDirty||!begin())return;setError('');try{setSelected(await api<Source>(`/months/${draft.month}/sources/${source.id}`))}catch(e){setError((e as Error).message)}finally{end()}}
  async function reread(){if(!selected||reviewDirty||!begin())return;setError('');let updated:Draft|undefined;try{const r=await api<{draft:Draft;batch:Source}>(`/months/${draft.month}/sources/${selected.id}/reread`,'POST',{expected_revision:draft.revision},120000);updated=r.draft;setSelected(r.batch);setMessage('새 읽기 후보를 만들었습니다. 기존 채택 원본은 유지됩니다.');await refresh()}catch(e){setError((e as Error).message)}finally{end(updated)}}
  async function adopt(){
    if(!selected||reviewDirty||!begin())return;setError('');let updated:Draft|undefined;
    try{
      const prior=sources.find(s=>s.role===selected.role&&s.selected);
      updated=await api<Draft>(`/months/${draft.month}/sources/${selected.id}/select`,'POST',{expected_revision:draft.revision,previous_batch_id:prior?.id??null});
      setSelected({...selected,selected:1});setMessage(prior?'채택 원본을 교체했습니다. 이전 원본과 교체 이력은 보존됩니다.':'이번 달 원본으로 선택했습니다. 마감 계산·확정은 아직 실행되지 않습니다.');await refresh();
    }catch(e){setError((e as Error).message)}finally{end(updated)}
  }
  const prior=selected&&sources.find(s=>s.role===selected.role&&s.selected&&s.id!==selected.id);
  const filtered=selected?.records?.filter(r=>!query.trim()||`${r.part} ${JSON.stringify(r.evidence._normalized?.value??'')}`.toLowerCase().includes(query.trim().toLowerCase()));
  return <section className="paper sources" aria-label="원본 자료 등록">
    <div className="section-head"><h2>원본 자료 등록 · {draft.month}</h2><button disabled={otherDisabled||loading} onClick={()=>void refresh()}>목록 새로 읽기</button></div>
    <div className="source-body"><p>희성·유미코아 원본과 ERP 입고·수불, 글로비스 실제 입고 자료를 읽고 검산합니다. 수불은 창고와 입출고 처리 종류를 구분해 보관합니다.</p>
      <div className="source-controls"><label>자료 종류<select aria-label="자료 종류" disabled={otherDisabled} value={role} onChange={e=>{setRole(e.target.value);setFile(undefined);setPeriodConfirmed(false)}}>{Object.entries(labels).map(([v,l])=><option key={v} value={v}>{l} ({v==='heesung_carryover'?'PDF':'XLSX'})</option>)}</select></label>
      <label>자료 기준월<input aria-label="자료 기준월" readOnly value={period}/></label>
      <label>원본 파일<input key={role} aria-label="원본 파일" type="file" accept={role==='heesung_carryover'?'.pdf':'.xlsx'} disabled={otherDisabled} onChange={e=>{setFile(e.target.files?.[0]);setPeriodConfirmed(false)}}/></label>
      <button className="primary" disabled={otherDisabled||!file||loading||(needsPeriod&&!periodConfirmed)} onClick={()=>void register()}>원본 보관·읽기</button></div>
      {needsPeriod&&<label className="period-confirm"><input type="checkbox" disabled={otherDisabled} checked={periodConfirmed} onChange={e=>setPeriodConfirmed(e.target.checked)}/> {(role.endsWith('_master')||role==='price_policy')?`${period}에 적용할 기준 자료임을 확인했습니다.`:`${period} 전체 기간의 자료임을 확인했습니다.`}</label>}
      <p className="hint">해당 기준월 전체 자료를 선택해 주세요. 같은 종류는 한 파일을 채택하며 수정본은 검토 후 교체합니다. 원본 파일은 변경하지 않습니다.</p>
      {error&&<p className="error" role="alert">{error}</p>}{message&&<p className="source-message" role="status">{message}</p>}
      <div className="table-wrap"><table><thead><tr><th>원본 파일</th><th>자료 종류</th><th>기준월</th><th>등록 시각</th><th>상태</th><th>검토</th></tr></thead><tbody>{sources.map(s=><tr key={s.id}><td>{s.filename}</td><td>{label(s.role)}</td><td>{s.source_period}</td><td>{new Date(s.created_at).toLocaleString('ko-KR')}</td><td>{status(s)}</td><td><button disabled={otherDisabled} onClick={()=>void inspect(s)}>내용 보기</button></td></tr>)}</tbody></table></div>
      {!sources.length&&<p>{loading?'등록 자료를 읽고 있습니다.':error?'자료 목록을 확인하지 못했습니다.':'아직 등록한 자료가 없습니다.'}</p>}
      {selected&&<div className="source-detail"><h3>{selected.filename}</h3><a href={`/api/months/${draft.month}/sources/${selected.id}/original`}>보관 원본 다운로드</a>
        <button disabled={otherDisabled||loading} onClick={()=>void reread()}>원본 다시 읽기 · 새 후보</button>
        {selected.result.summary.row_count!==undefined&&<p>원문 {selected.result.summary.row_count}행 · 품번 {selected.result.summary.part_count}종{selected.result.summary.quantity_total!==undefined&&<> · {selected.result.summary.quantity_label??(selected.role==='erp_receipts'?'촉매 입고':selected.role==='heesung_shipments'?'출하':'적송재고 인식')} 합계 {selected.result.summary.quantity_total}개</>} <strong>(최종 마감 확정 전)</strong></p>}
        {['erp_receipts','product_stock','semi_stock'].includes(selected.role)&&<p className="hint">조회 기간: 사용자 확인 {selected.source_period}. 파일 본문에는 조회 날짜가 없습니다. 수불 처리 항목은 경로·BOM 연결 후 배분 기준으로 선택합니다.</p>}
        {selected.result.summary.notices?.map((notice,i)=><p className="hint" key={i}>{notice}</p>)}
        {selected.result.issues.length>0&&<div className="source-issues"><h4>확인할 항목 {selected.result.issues.length}건</h4>{selected.result.issues.map((i,n)=><p key={n}><strong>{i.location}</strong> — {i.message}</p>)}</div>}
        {prior&&<p>현재 사용하는 <strong>{prior.filename}</strong>을 이 자료로 교체합니다. 이전 파일은 남습니다.</p>}
        <button className="primary" disabled={otherDisabled||loading||selected.status!=='ready'||Boolean(sources.find(s=>s.id===selected.id)?.selected)} onClick={()=>void adopt()}>{prior?'이 수정본으로 교체':'이번 달 원본으로 사용'}</button>
        {!!selected.records?.length&&selected.role==='heesung_carryover'&&<PdfReview key={selected.id} source={selected} draft={draft} disabled={disabled} onDirty={v=>{setReviewDirty(v);onDirty(v)}} begin={begin} end={end} onReviewed={s=>{setSelected(s);void refresh()}}/>}
        {!!selected.records?.length&&selected.role!=='heesung_carryover'&&<label className="source-filter">품번·창고·거래처 검색 <input value={query} onChange={e=>setQuery(e.target.value)} aria-label="품번·창고·거래처 검색"/> <span>{filtered?.length} / {selected.records.length}행</span></label>}
        {!!selected.records?.length&&selected.role!=='heesung_carryover'&&<div className="table-wrap evidence-table"><table><thead><tr><th>원본 위치</th><th>품번</th><th>{selected.role==='umicore_statement'?'고객사 / 원문 수량':selected.role.endsWith('_stock')?'창고 / 입출고 처리':'수량 / 구분'}</th><th>셀 근거</th></tr></thead><tbody>{filtered?.map(r=>{
          const normalized=r.evidence._normalized?.value as {kind?:string;prior?:string;held?:string;note?:string;quantities?:Record<string,string>;key?:string;basis?:string;price?:string;price_kind?:string;period?:string;reason?:string;plan_price?:string;months?:Record<string,string>;supplier?:string;components?:{part:string;usage:string}[];path?:string;plant?:string;destination?:string;state?:string;use?:string;warehouse?:string;customer?:string;receipt_date?:string;receipt_ids?:Record<string,string>;metrics?:Record<string,string|null>;included?:boolean;by_customer?:Record<string,string|null>}|undefined;
          return <tr key={r.ordinal}><td>{r.sheet} · {r.row_number}행</td><td>{r.part||'품번 확인 필요'}</td><td>{normalized?.kind==='historical_pending'?<>{normalized.destination}<div>전월 이월 {normalized.prior}개 / 기존 미마감 {normalized.held}개</div><div>{normalized.reason} {normalized.note}</div></>:(normalized?.kind==='촉매총량'||normalized?.kind==='공장수량')?<>{normalized.kind} · {normalized.key}{Object.entries(normalized.quantities??{}).map(([k,v])=><div key={k}>{k}: {v}개</div>)}<div>{normalized.reason}</div><div>{normalized.basis}</div></>:normalized?.kind==='price'?<>ERP 단가: {normalized.price}원</>:normalized?.kind==='price_policy'?<>{normalized.period} · {normalized.destination}<div>{normalized.price_kind}: {normalized.price}원</div><div>{normalized.reason}</div></>:normalized?.kind==='plan'?<>{normalized.destination??normalized.supplier}<div>계획 원본 단가: {normalized.plan_price}원</div>{Object.entries(normalized.months??{}).map(([m,q])=><div key={m}>{m}: {q}개</div>)}</>:normalized?.kind==='bom'?<>{normalized.use}<div>{normalized.customer}</div>{normalized.components?.map((c,i)=><div key={i}>{c.part} × {c.usage}</div>)}</>:normalized?.kind==='route'?<>{normalized.path}<div>{normalized.plant} / {normalized.destination}</div><div>{normalized.state}</div></>:normalized?.metrics?<><strong>{normalized.warehouse??normalized.customer}</strong>{Object.entries(normalized.metrics).map(([k,v])=><div key={k}>{k}: {v??(selected.role==='umicore_statement'&&['1차 마감 표기','2차 마감 표기'].includes(k)?'미기재':'확인 필요')}</div>)}</>:<>{r.quantity??'확인 필요'}{normalized?.receipt_date&&<div>입고일: {normalized.receipt_date}</div>}{normalized?.receipt_ids&&Object.entries(normalized.receipt_ids).map(([k,v])=><div key={k}>{k}: {v}</div>)}{normalized?.included===false&&<strong> · 컨버터 제외</strong>}{normalized?.by_customer&&<details><summary>거래처별 입고</summary>{Object.entries(normalized.by_customer).map(([k,v])=><div key={k}>{k}: {v??'확인 필요'}</div>)}</details>}</>}</td><td><details><summary>원문 보기</summary>{Object.entries(r.evidence).filter(([cell])=>cell!=='_normalized').map(([cell,e])=><p key={cell}>{cell} {e.label}: {String(e.value??'공란')}{e.formula&&` (수식: ${e.formula})`}</p>)}</details></td></tr>
        })}</tbody></table></div>}
      </div>}
    </div>
  </section>
}
