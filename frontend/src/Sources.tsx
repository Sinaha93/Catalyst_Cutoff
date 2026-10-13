import {useEffect, useState} from 'react';
import {api, upload, type Draft} from './api';
import {PdfReview} from './PdfReview';

export type Source = {id:string; filename:string; created_at:string; role:string; source_period:string; selected:number; ever_selected?:number; status:string;
  result:{summary:{row_count?:number;part_count?:number;quantity_total?:string;printed_total?:string;period_confirmed?:boolean};issues:{code:string;location:string;message:string}[]};
  records?:{ordinal:number;sheet:string;row_number:number;part:string;quantity:string|null;evidence:Record<string,{label?:string;value?:unknown;formula?:string|null;peer_quantity?:string;reviewed?:boolean}>}[]};
const label=(role:string)=>role==='heesung_shipments'?'희성 출하 원본':'희성 전월 적송재고 PDF';
const status=(s:Source)=>s.selected?'이번 달 사용':s.status==='ready'?'읽기 검산 완료':'확인 필요';
function previousMonth(month:string){const [y,m]=month.split('-').map(Number);return `${m===1?y-1:y}-${String(m===1?12:m-1).padStart(2,'0')}`}

export function Sources({draft,disabled,begin,end,onDirty}:{onDirty:(dirty:boolean)=>void;draft:Draft;disabled:boolean;begin:()=>boolean;end:(d?:Draft)=>void}) {
  const [sources,setSources]=useState<Source[]>([]),[selected,setSelected]=useState<Source>();
  const [role,setRole]=useState('heesung_shipments'),[file,setFile]=useState<File>();
  const [error,setError]=useState(''),[message,setMessage]=useState(''),[loading,setLoading]=useState(false);
  const [reviewDirty,setReviewDirty]=useState(false);
  const otherDisabled=disabled||reviewDirty;
  const period=role==='heesung_shipments'?draft.month:previousMonth(draft.month);
  async function refresh(){setLoading(true);setError('');try{setSources(await api<Source[]>(`/months/${draft.month}/sources`))}catch(e){setError((e as Error).message)}finally{setLoading(false)}}
  useEffect(()=>{let active=true;setLoading(true);api<Source[]>(`/months/${draft.month}/sources`).then(s=>{if(active)setSources(s)}).catch(e=>{if(active)setError(e.message)}).finally(()=>{if(active)setLoading(false)});return()=>{active=false}},[draft.month,draft.revision]);
  async function register(){
    if(!file||reviewDirty||!begin())return;setError('');setMessage('');let updated:Draft|undefined;
    try{
      const params=new URLSearchParams({role,source_period:period,filename:file.name,expected_revision:String(draft.revision)});
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
      setSelected({...selected,selected:1});setMessage(prior?'채택 원본을 교체했습니다. 이전 원본과 교체 이력은 보존됩니다.':'이번 달 출하 원본으로 선택했습니다. 마감 계산·확정은 아직 실행되지 않습니다.');await refresh();
    }catch(e){setError((e as Error).message)}finally{end(updated)}
  }
  const prior=selected&&sources.find(s=>s.role===selected.role&&s.selected&&s.id!==selected.id);
  return <section className="paper sources" aria-label="원본 자료 등록">
    <div className="section-head"><h2>원본 자료 등록 · {draft.month}</h2><button disabled={otherDisabled||loading} onClick={()=>void refresh()}>목록 새로 읽기</button></div>
    <div className="source-body"><p>희성 출하 XLSX와 전월 적송재고 PDF를 읽습니다. PDF 인식 결과는 원본 이미지와 대조한 뒤 채택합니다.</p>
      <div className="source-controls"><label>자료 종류<select aria-label="자료 종류" disabled={otherDisabled} value={role} onChange={e=>{setRole(e.target.value);setFile(undefined)}}><option value="heesung_shipments">희성 출하 원본 (XLSX)</option><option value="heesung_carryover">희성 전월 적송재고 (PDF)</option></select></label>
      <label>자료 기준월<input aria-label="자료 기준월" readOnly value={period}/></label>
      <label>원본 파일<input key={role} aria-label="원본 파일" type="file" accept={role==='heesung_shipments'?'.xlsx':'.pdf'} disabled={otherDisabled} onChange={e=>setFile(e.target.files?.[0])}/></label>
      <button className="primary" disabled={otherDisabled||!file||loading} onClick={()=>void register()}>원본 보관·읽기</button></div>
      <p className="hint">해당 기준월 전체 자료를 선택해 주세요. 같은 종류는 한 파일을 채택하며 수정본은 검토 후 교체합니다. 원본 파일은 변경하지 않습니다.</p>
      {error&&<p className="error" role="alert">{error}</p>}{message&&<p className="source-message" role="status">{message}</p>}
      <div className="table-wrap"><table><thead><tr><th>원본 파일</th><th>자료 종류</th><th>기준월</th><th>등록 시각</th><th>상태</th><th>검토</th></tr></thead><tbody>{sources.map(s=><tr key={s.id}><td>{s.filename}</td><td>{label(s.role)}</td><td>{s.source_period}</td><td>{new Date(s.created_at).toLocaleString('ko-KR')}</td><td>{status(s)}</td><td><button disabled={otherDisabled} onClick={()=>void inspect(s)}>내용 보기</button></td></tr>)}</tbody></table></div>
      {!sources.length&&<p>{loading?'등록 자료를 읽고 있습니다.':error?'자료 목록을 확인하지 못했습니다.':'아직 등록한 자료가 없습니다.'}</p>}
      {selected&&<div className="source-detail"><h3>{selected.filename}</h3><a href={`/api/months/${draft.month}/sources/${selected.id}/original`}>보관 원본 다운로드</a>
        <button disabled={otherDisabled||loading} onClick={()=>void reread()}>원본 다시 읽기 · 새 후보</button>
        {selected.result.summary.row_count!==undefined&&<p>원문 {selected.result.summary.row_count}행 · 촉매 {selected.result.summary.part_count}종 · {selected.role==='heesung_shipments'?'출하':'적송재고 인식'} 합계 {selected.result.summary.quantity_total}개 <strong>(마감 수량 아님)</strong></p>}
        {selected.result.issues.length>0&&<div className="source-issues"><h4>확인할 항목 {selected.result.issues.length}건</h4>{selected.result.issues.map((i,n)=><p key={n}><strong>{i.location}</strong> — {i.message}</p>)}</div>}
        {prior&&<p>현재 사용하는 <strong>{prior.filename}</strong>을 이 자료로 교체합니다. 이전 파일은 남습니다.</p>}
        <button className="primary" disabled={otherDisabled||loading||selected.status!=='ready'||Boolean(sources.find(s=>s.id===selected.id)?.selected)} onClick={()=>void adopt()}>{prior?'이 수정본으로 교체':'이번 달 원본으로 사용'}</button>
        {!!selected.records?.length&&selected.role==='heesung_carryover'&&<PdfReview key={selected.id} source={selected} draft={draft} disabled={disabled} onDirty={v=>{setReviewDirty(v);onDirty(v)}} begin={begin} end={end} onReviewed={s=>{setSelected(s);void refresh()}}/>}
        {!!selected.records?.length&&selected.role==='heesung_shipments'&&<div className="table-wrap evidence-table"><table><thead><tr><th>원본 위치</th><th>촉매 품번</th><th>출하 수량</th><th>셀 근거</th></tr></thead><tbody>{selected.records.map(r=><tr key={r.ordinal}><td>{r.sheet} · {r.row_number}행</td><td>{r.part||'품번 확인 필요'}</td><td>{r.quantity??'확인 필요'}</td><td><details><summary>원문 보기</summary>{Object.entries(r.evidence).map(([cell,e])=><p key={cell}>{cell} {e.label}: {String(e.value??'공란')}{e.formula&&` (수식: ${e.formula})`}</p>)}</details></td></tr>)}</tbody></table></div>}
      </div>}
    </div>
  </section>
}
