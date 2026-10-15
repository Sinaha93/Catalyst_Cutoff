import {useEffect, useState, useRef} from 'react';
import {api, upload, type Draft} from './api';
import type {HelpRequest} from './IssueHelp';
import {PdfReview} from './PdfReview';
import type {SourceProgress} from './Workflow';
import type {Page} from './navigation';

export type Source = {managed_version?:string|null;id:string; filename:string; created_at:string; role:string; source_period:string; selected:number; ever_selected?:number; status:string;
  result:{summary:{row_count?:number;part_count?:number;quantity_total?:string;printed_total?:string;period_confirmed?:boolean;quantity_label?:string;notices?:string[]};issues:{code:string;location:string;message:string}[]};
  records?:{ordinal:number;sheet:string;row_number:number;part:string;quantity:string|null;evidence:Record<string,{label?:string;value?:unknown;formula?:string|null;peer_quantity?:string;reviewed?:boolean}>}[]};
const labels:Record<string,string>={umicore_carryover:'유미코아 전월 적송재고 PDF',heesung_shipments:'희성 출하 원본',heesung_carryover:'희성 전월 적송재고 PDF',erp_receipts:'ERP 촉매 입고',product_stock:'제품 창고 수불',semi_stock:'반제품 창고 수불',umicore_statement:'유미코아 납품 Summary',glovis_receipts:'글로비스 실제 입고',bom_master:'BOM 기준',route_master:'통합 경로 기준',price_master:'촉매 단가',price_policy:'이전 예외 단가(보관)',plan_master:'월계획',allocation_inputs:'배분 수량 근거',comparison_report:'기존 보고서 미정산 비교'};
const label=(role:string)=>labels[role]??role;
const status=(s:Source)=>s.selected?'이번 달 사용':s.status==='ready'?'읽기 검산 완료':'확인 필요';
function previousMonth(month:string){const [y,m]=month.split('-').map(Number);return `${m===1?y-1:y}-${String(m===1?12:m-1).padStart(2,'0')}`}

export function Sources({helpRequest,draft,disabled,begin,end,onDirty,onProgress,onNavigate}:{helpRequest?:HelpRequest;onDirty:(dirty:boolean)=>void;draft:Draft;disabled:boolean;begin:()=>boolean;end:(d?:Draft)=>void;onProgress:(p:SourceProgress)=>void;onNavigate:(page:Page)=>void}) {
  const handledHelp=useRef(0);const [helpRoles,setHelpRoles]=useState<string[]>([]);const [helpFilter,setHelpFilter]=useState('');
  const [sources,setSources]=useState<Source[]>([]),[selected,setSelected]=useState<Source>();
  const [role,setRole]=useState('heesung_shipments'),[file,setFile]=useState<File>();
  const [error,setError]=useState(''),[message,setMessage]=useState(''),[loading,setLoading]=useState(false);
  const [reviewDirty,setReviewDirty]=useState(false);
  const [periodConfirmed,setPeriodConfirmed]=useState(false);
  const [loadedRevision,setLoadedRevision]=useState(-1);
  const [group,setGroup]=useState('monthly');
  const groups=[{id:'monthly',label:'이번 달 원본',roles:['heesung_shipments','heesung_carryover','umicore_statement','umicore_carryover','erp_receipts','product_stock','semi_stock','glovis_receipts']},{id:'plan',label:'월계획',roles:['plan_master']},{id:'extra',label:'추가 비교 자료',roles:['allocation_inputs','comparison_report']}];
  useEffect(()=>onProgress({month:draft.month,revision:loadedRevision,loading,error:Boolean(error),selected:sources.filter(s=>s.selected).length,registered:sources.length}),[sources,loadedRevision,loading,error,draft.month,onProgress]);
  const sourceDetailRef=useRef<HTMLDivElement>(null);
  const fileInputRef=useRef<HTMLInputElement>(null);
  useEffect(()=>{if(selected)sourceDetailRef.current?.scrollIntoView({block:'start'})},[selected?.id]);
  const [query,setQuery]=useState('');
  useEffect(()=>setQuery(helpFilter),[selected?.id,helpFilter]);
  const needsPeriod=['erp_receipts','product_stock','semi_stock','umicore_statement','glovis_receipts','bom_master','route_master','price_master','price_policy','plan_master','allocation_inputs','comparison_report'].includes(role);
  const otherDisabled=disabled||reviewDirty;
  const writeDisabled=otherDisabled||Boolean(draft.finalized);
  const period=role.endsWith('_carryover')?previousMonth(draft.month):draft.month;
  async function refresh(){setLoading(true);setError('');try{setSources((await api<Source[]>(`/months/${draft.month}/sources`)).filter(s=>!['bom_master','route_master','price_master','price_policy'].includes(s.role)));setLoadedRevision(draft.revision)}catch(e){setError((e as Error).message)}finally{setLoading(false)}}
  useEffect(()=>{let active=true;setLoading(true);api<Source[]>(`/months/${draft.month}/sources`).then(s=>{if(active){setSources(s.filter(b=>!['bom_master','route_master','price_master','price_policy'].includes(b.role)));setLoadedRevision(draft.revision)}}).catch(e=>{if(active)setError(e.message)}).finally(()=>{if(active)setLoading(false)});return()=>{active=false}},[draft.month,draft.revision]);
  useEffect(()=>{
    const request=helpRequest;
    if(!request||request.id===handledHelp.current||request.target.page!=='sources'||loadedRevision!==draft.revision||disabled||reviewDirty||file)return;
    handledHelp.current=request.id;
    const wanted=(request.target.sourceRoles??[]).filter(r=>groups.some(g=>g.roles.includes(r)));
    setHelpRoles(wanted);setHelpFilter(request.target.part&&request.target.part!=='*'?request.target.part:'');
    if(wanted.length===1){chooseHelpRole(wanted[0])}else{setSelected(undefined);setMessage(wanted.length?'확인할 자료 종류를 아래에서 선택해 주세요.':'문제가 발생한 품번을 검색 조건에 준비했습니다. 확인할 자료 종류를 선택해 주세요.')}
  },[helpRequest,loadedRevision,draft.revision,disabled,reviewDirty,file]);
  function chooseHelpRole(key:string){
    setRole(key);setGroup(groups.find(g=>g.roles.includes(key))!.id);setPeriodConfirmed(false);setError('');
    const candidate=sources.find(s=>s.role===key&&s.selected)??sources.find(s=>s.role===key);
    if(candidate){setLoading(true);api<Source>(`/months/${draft.month}/sources/${candidate.id}`).then(setSelected).catch(e=>setError(e.message)).finally(()=>setLoading(false))}
    else{setSelected(undefined);setMessage(`${label(key)} 파일을 선택해 주세요. 자료 기준월은 ${key.endsWith('_carryover')?previousMonth(draft.month):draft.month}로 준비했습니다.`);requestAnimationFrame(()=>fileInputRef.current?.focus())}
  }
  async function register(){
    if(!file||role==='price_policy'||draft.finalized||reviewDirty||!begin())return;setError('');setMessage('');let updated:Draft|undefined;
    try{
      const params=new URLSearchParams({role,source_period:period,filename:file.name,expected_revision:String(draft.revision),period_confirmed:String(periodConfirmed)});
      const r=await upload<{draft:Draft;batch:Source;duplicate:boolean}>(`/months/${draft.month}/sources?${params}`,file);
      updated=r.draft;setSelected(r.batch);setMessage(r.duplicate?'같은 파일이 이미 등록되어 있습니다. 중복 추가하지 않았습니다.':'원본을 보관했습니다. 읽기 결과를 확인한 뒤 이번 달 자료로 선택해 주세요.');
      await refresh();
    }catch(e){setError((e as Error).message)}finally{end(updated)}
  }
  async function inspect(source:Source){if(reviewDirty||!begin())return;setError('');try{setSelected(await api<Source>(`/months/${draft.month}/sources/${source.id}`))}catch(e){setError((e as Error).message)}finally{end()}}
  async function reread(){if(!selected||draft.finalized||reviewDirty||!begin())return;setError('');let updated:Draft|undefined;try{const r=await api<{draft:Draft;batch:Source}>(`/months/${draft.month}/sources/${selected.id}/reread`,'POST',{expected_revision:draft.revision},120000);updated=r.draft;setSelected(r.batch);setMessage('새 읽기 후보를 만들었습니다. 기존 채택 원본은 유지됩니다.');await refresh()}catch(e){setError((e as Error).message)}finally{end(updated)}}
  async function adopt(){
    if(!selected||draft.finalized||reviewDirty||!begin())return;setError('');let updated:Draft|undefined;
    try{
      const prior=sources.find(s=>s.role===selected.role&&s.selected);
      updated=await api<Draft>(`/months/${draft.month}/sources/${selected.id}/select`,'POST',{expected_revision:draft.revision,previous_batch_id:prior?.id??null});
      setSelected({...selected,selected:1});setMessage(prior?'채택 원본을 교체했습니다. 이전 원본과 교체 이력은 보존됩니다.':'이번 달 원본으로 선택했습니다. 마감 계산·확정은 아직 실행되지 않습니다.');await refresh();
    }catch(e){setError((e as Error).message)}finally{end(updated)}
  }
  function chooseRole(key:string){
    setRole(key);setGroup(groups.find(g=>g.roles.includes(key))!.id);setFile(undefined);setPeriodConfirmed(false);
    if(fileInputRef.current)fileInputRef.current.value='';
    const candidate=sources.find(s=>s.role===key&&s.selected)??sources.find(s=>s.role===key);
    if(candidate)void inspect(candidate);else setSelected(undefined);
  }
  const prior=selected&&sources.find(s=>s.role===selected.role&&s.selected&&s.id!==selected.id);
  const filtered=selected?.records?.filter(r=>!query.trim()||`${r.part} ${JSON.stringify(r.evidence._normalized?.value??'')}`.toLowerCase().includes(query.trim().toLowerCase()));
  return <section className="paper sources" aria-label="원본 자료 등록">
    <div className="section-head"><h2>원본 자료 등록 · {draft.month}</h2><button disabled={otherDisabled||loading} onClick={()=>void refresh()}>목록 새로 읽기</button></div>
    <div className="source-body"><div className="source-intro"><div><strong>{draft.finalized?'확정된 월의 원본 자료를 확인합니다.':'파일 등록 후 ‘이번 달 원본으로 사용’까지 선택해 주세요.'}</strong><p>{draft.finalized?'자료를 바꾸려면 확정·출력에서 새 확정 버전 작업을 시작해 주세요.':'① 자료 종류와 파일 선택 → ② 읽기 결과 확인 → ③ 이번 달 계산에 사용'}</p></div><button disabled={otherDisabled||loading||!sources.some(s=>s.selected)} onClick={()=>onNavigate('review')}>마감 검토로 이동 →</button></div>
      {helpRoles.length>1&&<div className="master-current"><strong>이번 문제와 관련된 자료</strong><div>{helpRoles.map(r=><button key={r} disabled={otherDisabled||loading} onClick={()=>chooseHelpRole(r)}>{label(r)}</button>)}</div></div>}
      <div className="source-groups" aria-label="자료 분류">{groups.map(g=><button key={g.id} aria-pressed={group===g.id} className={group===g.id?'chosen':''} disabled={otherDisabled} onClick={()=>chooseRole(g.roles.includes(role)?role:g.roles[0])}>{g.label}</button>)}</div>
      <div className="source-checklist">{groups.find(g=>g.id===group)!.roles.map(key=>{const used=sources.find(s=>s.role===key&&s.selected);const candidate=used??sources.find(s=>s.role===key);return <button key={key} className={role===key?'chosen':''} aria-pressed={role===key} disabled={otherDisabled||loading} onClick={()=>chooseRole(key)}><strong>{label(key)}</strong><span className={used?'source-used':''}>{used?'✓ 이번 달 사용':candidate?(candidate.status==='ready'?'읽기 완료 · 사용 선택 전':'내용 확인 필요'):'등록된 자료 없음'}</span></button>})}</div>
      <p className="hint">이번 달 실적과 월계획을 등록합니다. BOM·촉매 단가·경로 파일의 등록과 변경은 상단 기준 관리에서 진행합니다.</p>
      <div className="source-controls"><label>선택한 자료<input aria-label="선택한 자료" readOnly value={`${label(role)} (${role.endsWith('_carryover')?'PDF':'XLSX'})`}/></label>
      <label>자료 기준월<input aria-label="자료 기준월" readOnly value={period}/></label>
      <label>원본 파일<input key={role} ref={fileInputRef} aria-label="원본 파일" type="file" accept={role.endsWith('_carryover')?'.pdf':'.xlsx'} disabled={writeDisabled} onChange={e=>{setFile(e.target.files?.[0]);setPeriodConfirmed(false)}}/></label>
      <button className="primary" disabled={writeDisabled||!file||loading||(needsPeriod&&!periodConfirmed)} onClick={()=>void register()}>원본 보관·읽기</button></div>
      {role==='price_master'&&<p className="hint">품번별 기본 단가 파일 하나를 등록합니다. 가단가·예외 단가는 별도 파일 없이 마감 검토 → 촉매 선택 → 단가에서 수정합니다. 적용 월·마감처와 사유·근거를 함께 저장합니다.</p>}
      {needsPeriod&&<label className="period-confirm"><input type="checkbox" disabled={writeDisabled} checked={periodConfirmed} onChange={e=>setPeriodConfirmed(e.target.checked)}/> {(role.endsWith('_master')||role==='price_policy')?`${period}에 적용할 기준 자료임을 확인했습니다.`:`${period} 전체 기간의 자료임을 확인했습니다.`}</label>}
      <p className="hint">해당 기준월 전체 자료를 선택해 주세요. 같은 종류는 한 파일을 채택하며 수정본은 검토 후 교체합니다. 원본 파일은 변경하지 않습니다.</p>
      {error&&<p className="error" role="alert">{error}</p>}{message&&<p className="source-message" role="status">{message}</p>}
      <details className="source-history" open={!selected}><summary>등록 파일 목록 · {sources.length}개 / 이번 달 사용 {sources.filter(s=>s.selected).length}종</summary>      <div className="table-wrap"><table><thead><tr><th>원본 파일</th><th>자료 종류</th><th>기준월</th><th>등록 시각</th><th>상태</th><th>검토</th></tr></thead><tbody>{sources.map(s=><tr key={s.id}><td>{s.filename}</td><td>{label(s.role)}</td><td>{s.source_period}</td><td>{new Date(s.created_at).toLocaleString('ko-KR')}</td><td>{status(s)}</td><td><button disabled={otherDisabled} onClick={()=>void inspect(s)}>내용 보기</button></td></tr>)}</tbody></table></div>
</details>
      {!sources.length&&<p>{loading?'등록 자료를 읽고 있습니다.':error?'자료 목록을 확인하지 못했습니다.':'아직 등록한 자료가 없습니다.'}</p>}
      {selected&&<div className="source-detail" ref={sourceDetailRef}><h3>{selected.filename}</h3><p className="source-file-status">파일 상태: {status(sources.find(s=>s.id===selected.id)??selected)}</p><a href={`/api/months/${draft.month}/sources/${selected.id}/original`}>보관 원본 다운로드</a>
        {selected.role!=='price_policy'&&<button disabled={writeDisabled||loading} onClick={()=>void reread()}>원본 다시 읽기 · 새 후보</button>}
        {selected.result.summary.row_count!==undefined&&<p>원문 {selected.result.summary.row_count}행 · 품번 {selected.result.summary.part_count}종{selected.result.summary.quantity_total!==undefined&&<> · {selected.result.summary.quantity_label??(selected.role==='erp_receipts'?'촉매 입고':selected.role==='heesung_shipments'?'출하':'적송재고 인식')} 합계 {selected.result.summary.quantity_total}개</>} <strong>(최종 마감 확정 전)</strong></p>}
        {['erp_receipts','product_stock','semi_stock'].includes(selected.role)&&<p className="hint">조회 기간: 사용자 확인 {selected.source_period}. 파일 본문에는 조회 날짜가 없습니다. 수불 처리 항목은 경로·BOM 연결 후 배분 기준으로 선택합니다.</p>}
        {selected.result.summary.notices?.map((notice,i)=><p className="hint" key={i}>{notice}</p>)}
        {selected.result.issues.length>0&&<div className="source-issues"><h4>확인할 항목 {selected.result.issues.length}건</h4>{selected.result.issues.map((i,n)=><p key={n}><strong>{i.location}</strong> — {i.message}</p>)}</div>}
        {sources.find(s=>s.id===selected.id)?.managed_version&&<p className="source-message">이 항목은 프로그램 기준으로 관리 중입니다. 올린 파일은 <button className="inline-link" disabled={otherDisabled} onClick={()=>onNavigate('masters')}>기준 관리</button>에서 변경 내용을 비교한 뒤 새 버전으로 등록해 주세요.</p>}{prior&&!sources.find(s=>s.id===selected.id)?.managed_version&&<p>현재 사용하는 <strong>{prior.filename}</strong>을 이 자료로 교체합니다. 이전 파일은 남습니다.</p>}
        {selected.role==='price_policy'?<p className="hint">이전 예외 단가 파일은 보관·조회용입니다. 이번 달 가단가·예외 단가는 마감 검토에서 촉매를 선택하고 ‘단가’를 수정해 주세요.</p>:<button className="primary" disabled={writeDisabled||loading||Boolean(sources.find(s=>s.id===selected.id)?.managed_version)||selected.status!=='ready'||Boolean(sources.find(s=>s.id===selected.id)?.selected)} onClick={()=>void adopt()}>{prior?'이 수정본으로 교체':'이번 달 원본으로 사용'}</button>}
        {!!selected.records?.length&&selected.role.endsWith('_carryover')&&<PdfReview key={selected.id} source={selected} draft={draft} disabled={disabled||Boolean(draft.finalized)} onDirty={v=>{setReviewDirty(v);onDirty(v)}} begin={begin} end={end} onReviewed={s=>{setSelected(s);void refresh()}}/>}
        {!!selected.records?.length&&!selected.role.endsWith('_carryover')&&<label className="source-filter">품번·창고·거래처 검색 <input value={query} onChange={e=>setQuery(e.target.value)} aria-label="품번·창고·거래처 검색"/> <span>{filtered?.length} / {selected.records.length}행</span></label>}
        {!!selected.records?.length&&!selected.role.endsWith('_carryover')&&<div className="table-wrap evidence-table"><table><thead><tr><th>원본 위치</th><th>품번</th><th>{selected.role==='umicore_statement'?'고객사 / 원문 수량':selected.role.endsWith('_stock')?'창고 / 입출고 처리':'수량 / 구분'}</th><th>셀 근거</th></tr></thead><tbody>{filtered?.map(r=>{
          const normalized=r.evidence._normalized?.value as {kind?:string;prior?:string;held?:string;note?:string;quantities?:Record<string,string>;key?:string;basis?:string;price?:string;price_kind?:string;period?:string;reason?:string;plan_price?:string;months?:Record<string,string>;supplier?:string;components?:{part:string;usage:string}[];path?:string;plant?:string;destination?:string;state?:string;use?:string;warehouse?:string;customer?:string;receipt_date?:string;receipt_ids?:Record<string,string>;metrics?:Record<string,string|null>;included?:boolean;by_customer?:Record<string,string|null>}|undefined;
          return <tr key={r.ordinal}><td>{r.sheet} · {r.row_number}행</td><td>{r.part||'품번 확인 필요'}</td><td>{normalized?.kind==='historical_pending'?<>{normalized.destination}<div>전월 이월 {normalized.prior}개 / 기존 미마감 {normalized.held}개</div><div>{normalized.reason} {normalized.note}</div></>:(normalized?.kind==='촉매총량'||normalized?.kind==='공장수량')?<>{normalized.kind} · {normalized.key}{Object.entries(normalized.quantities??{}).map(([k,v])=><div key={k}>{k}: {v}개</div>)}<div>{normalized.reason}</div><div>{normalized.basis}</div></>:normalized?.kind==='price'?<>촉매 단가: {normalized.price}원</>:normalized?.kind==='price_policy'?<>{normalized.period} · {normalized.destination}<div>{normalized.price_kind}: {normalized.price}원</div><div>{normalized.reason}</div></>:normalized?.kind==='plan'?<>{normalized.destination??normalized.supplier}<div>계획 원본 단가: {normalized.plan_price}원</div>{Object.entries(normalized.months??{}).map(([m,q])=><div key={m}>{m}: {q}개</div>)}</>:normalized?.kind==='bom'?<>{normalized.use}<div>{normalized.customer}</div>{normalized.components?.map((c,i)=><div key={i}>{c.part} × {c.usage}</div>)}</>:normalized?.kind==='route'?<>{normalized.path}<div>{normalized.plant} / {normalized.destination}</div><div>{normalized.state}</div></>:normalized?.metrics?<><strong>{normalized.warehouse??normalized.customer}</strong>{Object.entries(normalized.metrics).map(([k,v])=><div key={k}>{k}: {v??(selected.role==='umicore_statement'&&['1차 마감 표기','2차 마감 표기'].includes(k)?'미기재':'확인 필요')}</div>)}</>:<>{r.quantity??'확인 필요'}{normalized?.receipt_date&&<div>입고일: {normalized.receipt_date}</div>}{normalized?.receipt_ids&&Object.entries(normalized.receipt_ids).map(([k,v])=><div key={k}>{k}: {v}</div>)}{normalized?.included===false&&<strong> · 컨버터 제외</strong>}{normalized?.by_customer&&<details><summary>거래처별 입고</summary>{Object.entries(normalized.by_customer).map(([k,v])=><div key={k}>{k}: {v??'확인 필요'}</div>)}</details>}</>}</td><td><details><summary>원문 보기</summary>{Object.entries(r.evidence).filter(([cell])=>cell!=='_normalized').map(([cell,e])=><p key={cell}>{cell} {e.label}: {String(e.value??'공란')}{e.formula&&` (수식: ${e.formula})`}</p>)}</details></td></tr>
        })}</tbody></table></div>}
      </div>}
    </div>
  </section>
}
