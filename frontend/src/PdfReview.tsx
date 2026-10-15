import {useState} from 'react';
import {api,type Draft} from './api';
import type {Source} from './Sources';

export function PdfReview({source,draft,disabled,begin,end,onReviewed,onDirty}:{onDirty:(dirty:boolean)=>void;source:Source;draft:Draft;disabled:boolean;begin:()=>boolean;end:(d?:Draft)=>void;onReviewed:(s:Source)=>void}){
 const [rows,setRows]=useState(()=>source.records!.map(r=>({ordinal:r.ordinal,part:r.part,quantity:r.quantity??'',peer_quantity:String(r.evidence.pdf?.peer_quantity??''),reviewed:Boolean(r.evidence.pdf?.reviewed)})));
 const [active,setActive]=useState(0),[printed,setPrinted]=useState(String(source.result.summary.printed_total??'')),[period,setPeriod]=useState(Boolean(source.result.summary.period_confirmed)),[reason,setReason]=useState(''),[error,setError]=useState('');
 const locked=disabled;
 const ownLabel=source.role==='umicore_carryover'?'월말 적송':'희성 수량';const peerLabel=source.role==='umicore_carryover'?'전월 + 공급 − 마감':'우신 수량';
 async function save(){if(!begin())return;setError('');let updated:Draft|undefined;try{const r=await api<{draft:Draft;batch:Source}>(`/months/${draft.month}/sources/${source.id}/review`,'POST',{expected_revision:draft.revision,rows,printed_total:printed,confirmed_period:period?source.source_period:'',reason});updated=r.draft;onReviewed(r.batch);onDirty(false)}catch(e){setError((e as Error).message)}finally{end(updated)}}
 return <div className="pdf-review" onChange={()=>onDirty(true)}><h4>PDF 인식 정정·확인</h4><p>PDF에 적힌 품번과 수량을 확인합니다. 업무상 이월 수량 조정은 통합 마감 검토에서 별도로 처리합니다.</p>
 <a href={`/api/months/${draft.month}/sources/${source.id}/preview`} target="_blank" rel="noreferrer">PDF 전체 이미지 보기</a>
 <div className="pdf-row-preview"><strong>원본 {active+1}행 · {source.role==='umicore_carryover'?'품번 / 전월 / 공급 / 마감 / 월말 적송':'순번 / 품번 / 희성 수량 / 우신 수량 / 차이 / 사유'}</strong><img alt={`PDF 원본 ${active+1}행`} src={`/api/months/${draft.month}/sources/${source.id}/preview?ordinal=${active}`}/></div>
 <div className="table-wrap"><table><thead><tr><th>원본</th><th>촉매 품번</th><th>{ownLabel}</th><th>{peerLabel}</th><th>행 확인</th></tr></thead><tbody>{rows.map((r,i)=><tr key={r.ordinal} className={active===i?'selected':''}><td><button disabled={disabled} onClick={()=>setActive(i)}>{i+1}행 보기</button></td><td><input aria-label={`${i+1}행 품번`} disabled={locked} value={r.part} onFocus={()=>setActive(i)} onChange={e=>setRows(rs=>rs.map((v,k)=>k===i?{...v,part:e.target.value,reviewed:false}:v))}/></td><td><input className="quantity-input" aria-label={`${i+1}행 ${ownLabel}`} disabled={locked} value={r.quantity} onFocus={()=>setActive(i)} onChange={e=>setRows(rs=>rs.map((v,k)=>k===i?{...v,quantity:e.target.value,reviewed:false}:v))}/></td><td><input className="quantity-input" aria-label={`${i+1}행 ${peerLabel}`} disabled={locked} value={r.peer_quantity} onFocus={()=>setActive(i)} onChange={e=>setRows(rs=>rs.map((v,k)=>k===i?{...v,peer_quantity:e.target.value,reviewed:false}:v))}/></td><td><input type="checkbox" aria-label={`${i+1}행 확인`} disabled={locked} checked={r.reviewed} onChange={e=>setRows(rs=>rs.map((v,k)=>k===i?{...v,reviewed:e.target.checked}:v))}/></td></tr>)}</tbody></table></div>
 <div className="source-controls"><label>PDF에 표시된 전월 말 적송 합계<input aria-label="PDF 표시 합계" disabled={locked} value={printed} onChange={e=>setPrinted(e.target.value)}/></label><label><input type="checkbox" aria-label="PDF 기준월 확인" disabled={locked} checked={period} onChange={e=>setPeriod(e.target.checked)}/>본문의 재고 기준월이 {source.source_period}임을 확인했습니다.</label></div>
 <label>인식 정정·확인 내용<input aria-label="인식 확인 내용" disabled={locked} value={reason} placeholder="원본과 대조한 정정·확인 내용을 적어 주세요" onChange={e=>setReason(e.target.value)}/></label>
 {error&&<p className="error" role="alert">{error}</p>}
 <button disabled={locked||!period||!printed||!reason.trim()} onClick={()=>void save()}>인식 정정·확인 저장</button>
 <button disabled={locked} onClick={()=>{setRows(source.records!.map(r=>({ordinal:r.ordinal,part:r.part,quantity:r.quantity??'',peer_quantity:String(r.evidence.pdf?.peer_quantity??''),reviewed:Boolean(r.evidence.pdf?.reviewed)})));setPrinted(String(source.result.summary.printed_total??''));setPeriod(Boolean(source.result.summary.period_confirmed));setReason('');onDirty(false)}}>인식 입력 취소</button>
 <p className="hint">미확인 행·중복 품번·합계 차이가 남으면 자료를 채택할 수 없습니다. 이미 채택한 결과를 정정하면 별도 정정본을 만들며 기존 채택본은 유지됩니다.</p>
 </div>
}
