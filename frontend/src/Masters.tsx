import {ChoiceSelect,ChoiceManagerButton,DestinationSelect,StateSelect,WarehouseSelect} from './Choices';
import {useEffect,useState,useRef} from 'react';
import {api,upload,type Draft} from './api';
import './masters.css';
import {BomEntry} from './BomEntry';
import {SupplierSelect} from './PartnerSelect';
import {MasterRepair} from './MasterRepair';
import type {HelpRequest} from './IssueHelp';

type Row={part:string;[key:string]:unknown};
type Version={id:string;role:string;version:number;effective_from:string;effective_to:string|null;reason:string};
type Overview={revision:number;versions:Version[];selected:Record<string,string>;candidates:{id:string;role:string;filename:string;status:string;selected?:boolean}[]};
type Change={key:string;change:string;before:Row|null;after:Row|null};
type Proposal={fingerprint:string;changes:Change[]};
type ResetPreview={role:string;label:string;revision:number;fingerprint:string;version_count:number;source_count:number;file_count:number;blocked:string[]};
type FileResult={id:string;filename:string;status:string;result:{summary:{row_count?:number;part_count?:number};issues:{location:string;message:string}[]}};
type Props={helpRequest?:HelpRequest;draft:Draft;disabled:boolean;onDirty:(v:boolean)=>void;begin:()=>boolean;end:(d?:Draft)=>void};
const cardOrder=['bom_master','price_master','route_master'];
const cardLabels:Record<string,string>={bom_master:'BOM',price_master:'촉매 단가',route_master:'경로·공장'};
const labels:Record<string,string>={route_master:'물류 경로·공장',bom_master:'BOM 버전',price_master:'촉매 단가'};
const fieldNames:Record<string,string>={part:'품번',route_id:'경로 번호',supplier:'촉매사',path:'납품 경로',plant:'상세 마감공장',destination:'ERP 마감처',state:'처리 상태',note:'비고',source_role:'집계 자료',warehouses:'집계 창고',metric:'수량 항목',included:'집계 포함',price:'적용 단가',price_kind:'단가 구분',reason:'사유',basis:'근거',customer:'고객사',components:'촉매 구성',use:'촉매 사용'};
function describe(row:Row|null){if(!row)return '없음';return Object.entries(row).filter(([k])=>!['kind','period','raw_part'].includes(k)).map(([k,v])=>`${fieldNames[k]??k}: ${typeof v==='object'?JSON.stringify(v):typeof v==='boolean'?(v?'포함':'추적만'):String(v)}`).join('\n')}
function Changes({changes}:{changes:Change[]}){return <div className="table-wrap master-diff"><table><thead><tr><th>대상</th><th>구분</th><th>변경 전</th><th>변경 후</th></tr></thead><tbody>{changes.map(c=><tr key={c.key}><td>{c.key}</td><td>{c.change}</td><td>{describe(c.before)}</td><td>{describe(c.after)}</td></tr>)}</tbody></table>{!changes.length&&<p>기준 내용의 변경이 없습니다. 적용 기간과 변경 사유를 확인해 주세요.</p>}</div>}

export function Masters({helpRequest,draft,disabled,onDirty,begin,end}:Props){
 const [repairContext,setRepairContext]=useState<HelpRequest['target']>();
 const [bomEntry,setBomEntry]=useState(false);const [bomContext,setBomContext]=useState<HelpRequest['target']>();
 const [resetPreview,setResetPreview]=useState<ResetPreview>();const [resetConfirmed,setResetConfirmed]=useState(false);
 const fileInputRef=useRef<HTMLInputElement>(null);
 const [file,setFile]=useState<File>();const [fileResult,setFileResult]=useState<FileResult>();
 const [overviewError,setOverviewError]=useState(false);
 const [overview,setOverview]=useState<Overview>();const [role,setRole]=useState('route_master');const [version,setVersion]=useState('');
 const [mode,setMode]=useState('native');const [batch,setBatch]=useState('');const [rows,setRows]=useState<Row[]>([]);const [index,setIndex]=useState(0);const [query,setQuery]=useState('');
 const [from,setFrom]=useState(draft.month);const [to,setTo]=useState('');const [reason,setReason]=useState('');
 const [proposal,setProposal]=useState<Proposal>();const [selection,setSelection]=useState<{version_id:string;changes:Change[]}>();
 const [error,setError]=useState('');const [message,setMessage]=useState('');const [dirty,setDirty]=useState(false);const [loading,setLoading]=useState(false);
 async function refresh(){setOverviewError(false);try{setOverview(await api<Overview>(`/months/${draft.month}/masters`))}catch(e){setOverviewError(true);setError((e as Error).message)}}
 useEffect(()=>{void refresh();setSelection(undefined)},[draft.id,draft.revision]);
 function chooseRole(key:string){
  if(key===role)return;
  setRepairContext(undefined);setBomEntry(false);setBomContext(undefined);setResetPreview(undefined);setResetConfirmed(false);
  if(fileInputRef.current)fileInputRef.current.value='';
  setFile(undefined);setFileResult(undefined);setRole(key);setMode(key==='bom_master'?'excel':'native');setRows([]);setVersion('');setBatch('');setProposal(undefined);setSelection(undefined);setError('');setMessage('');setQuery('');
 }
 const handledHelp=useRef(0);
 useEffect(()=>{if(!helpRequest||helpRequest.id===handledHelp.current||!helpRequest.target.masterRole||dirty)return;handledHelp.current=helpRequest.id;chooseRole(helpRequest.target.masterRole);setRepairContext(undefined);setBomEntry(false);if(helpRequest.target.part&&helpRequest.target.part!=='*'){if(helpRequest.target.masterRole==='bom_master'){setBomContext(helpRequest.target);setBomEntry(true)}else setRepairContext(helpRequest.target)}else requestAnimationFrame(()=>document.querySelector('.master-apply')?.scrollIntoView({block:'center'}))},[helpRequest,dirty]);
 function registrationStatus(key:string){
  if(overviewError)return {kind:'warning',text:'상태 확인 실패',detail:'목록을 다시 확인해 주세요.',pending:''};
  if(!overview||overview.revision!==draft.revision)return {kind:'neutral',text:'상태 확인 중…',detail:'',pending:''};
  const versions=overview.versions.filter(v=>v.role===key);
  const active=versions.find(v=>v.id===overview.selected[key]);
  const applicable=(v:Version)=>v.effective_from<=draft.month&&(!v.effective_to||v.effective_to>=draft.month);
  const waiting=versions.find(v=>applicable(v)&&v.id!==active?.id&&(!active||v.version>active.version));
  const files=overview.candidates.filter(c=>c.role===key);
  const source=files.find(c=>c.selected);
  const pending=waiting?`v${waiting.version} 저장됨 · 적용 대기`:'';
  if(active){
   if(!applicable(active))return {kind:'warning',text:'적용 기간 확인 필요',detail:`v${active.version} · ${active.effective_from}부터`,pending};
   return {kind:'used',text:'✓ 이번 달 사용',detail:`v${active.version} · ${active.effective_from}부터${active.effective_to?` ${active.effective_to}까지`:''}`,pending};
  }
  if(overview.selected[key])return {kind:'warning',text:'적용 기준 확인 필요',detail:'적용한 버전 정보를 찾지 못했습니다.',pending};
  if(source)return {kind:source.status==='ready'?'used':'warning',text:source.status==='ready'?'✓ 이번 달 사용':'적용 원본 확인 필요',detail:`파일 기준 · ${source.filename}`,pending};
  if(waiting)return {kind:'warning',text:'기준 저장됨 · 이번 달 적용 전',detail:`v${waiting.version}`,pending:''};
  if(files.some(c=>c.status==='ready'))return {kind:'neutral',text:'파일 읽기 완료 · 기준 저장 전',detail:'비교·저장 후 이번 달에 적용해 주세요.',pending:''};
  if(files.length)return {kind:'warning',text:'등록 파일 확인 필요',detail:'파일의 읽기 결과를 확인해 주세요.',pending:''};
  if(versions.length)return {kind:'warning',text:'이번 달 적용 가능한 기준 없음',detail:'기준 버전의 적용 기간을 확인해 주세요.',pending:''};
  return {kind:'neutral',text:'등록된 기준 없음',detail:'기준 파일을 등록해 주세요.',pending:''};
 }
 function changed(){setDirty(true);onDirty(true);setProposal(undefined);setSelection(undefined);setMessage('')}
 function discard(){if(fileInputRef.current)fileInputRef.current.value='';setFile(undefined);setFileResult(undefined);setDirty(false);onDirty(false);setRows([]);setVersion('');setBatch('');setReason('');setProposal(undefined);setSelection(undefined);setMessage('입력 중인 기준 편집을 취소했습니다. 저장한 버전은 유지됩니다.')}
 async function loadVersion(id:string){setError('');setLoading(true);try{const v=await api<Version&{payload:{records:{part:string;evidence:{_normalized:{value:Record<string,unknown>}}}[]}}>(`/masters/${id}`);setRows(v.payload.records.map(r=>role==='price_master'?{part:r.part,price:r.evidence._normalized.value.price}:{part:r.part,...r.evidence._normalized.value}));setVersion(id);setIndex(0);setFrom(draft.month);setTo('');setProposal(undefined);setSelection(undefined);setReason('');}catch(e){setError((e as Error).message)}finally{setLoading(false)}}
 useEffect(()=>{if(!repairContext&&!version&&!dirty&&overview?.selected[role])void loadVersion(overview.selected[role])},[overview?.selected[role],role]);
 useEffect(()=>{
  if(repairContext||role!=='price_master'||version||dirty||overview?.selected.price_master)return;
  const source=overview?.candidates.find(b=>b.role==='price_master'&&b.selected&&b.status==='ready');
  if(!source)return;
  let active=true;setLoading(true);
  api<{records:{part:string;evidence:{_normalized:{value:{price:string}}}}[]}>(`/months/${draft.month}/sources/${source.id}`).then(b=>{
   if(active){setRows(b.records.map(r=>({part:r.part,price:r.evidence._normalized.value.price})));setIndex(0)}
  }).catch(e=>{if(active)setError((e as Error).message)}).finally(()=>{if(active)setLoading(false)});
  return()=>{active=false};
 },[role,version,dirty,overview?.selected.price_master,overview?.candidates.find(b=>b.role==='price_master'&&b.selected)?.id,draft.id]);
 async function previewReset(){
  setLoading(true);setError('');setResetConfirmed(false);
  try{setResetPreview(await api<ResetPreview>(`/months/${draft.month}/masters/reset-preview?role=${role}`))}catch(e){setError((e as Error).message)}finally{setLoading(false)}
 }
 async function resetMaster(){
  if(!resetPreview||resetPreview.role!==role||!resetConfirmed||!begin())return;
  setLoading(true);setError('');let updated:Draft|undefined;
  try{
   const r=await api<{draft:Draft;warning:string|null}>(`/months/${draft.month}/masters/reset`,'POST',{role,expected_revision:resetPreview.revision,fingerprint:resetPreview.fingerprint,confirmation:resetPreview.label+' 초기화'});
   updated=r.draft;discard();setOverview(undefined);setResetPreview(undefined);setResetConfirmed(false);await refresh();
   setMessage(r.warning??`${resetPreview.label}의 등록 버전·파일을 초기화했습니다. 기준 파일을 다시 등록해 주세요.`);
  }catch(e){setError((e as Error).message)}finally{end(updated);setLoading(false)}
 }
 async function inspectFile(id:string){
  setLoading(true);setError('');try{setFileResult(await api<FileResult>(`/months/${draft.month}/sources/${id}`))}catch(e){setError((e as Error).message)}finally{setLoading(false)}
 }
 async function registerFile(){
  if(!file||draft.finalized||!begin())return;
  setError('');setLoading(true);let updated:Draft|undefined;
  try{
   const params=new URLSearchParams({role,source_period:draft.month,filename:file.name,expected_revision:String(draft.revision),period_confirmed:'true'});
   const r=await upload<{draft:Draft;batch:FileResult;duplicate:boolean}>(`/months/${draft.month}/sources?${params}`,file);
   updated=r.draft;setFileResult(r.batch);setMode('excel');setBatch(r.batch.status==='ready'?r.batch.id:'');setFile(undefined);if(fileInputRef.current)fileInputRef.current.value='';
   setProposal(undefined);setSelection(undefined);setDirty(true);onDirty(true);await refresh();
   setMessage(r.batch.status==='ready'?'기준 파일을 읽었습니다. 변경 사유를 입력하고 비교·저장·이번 달 적용을 진행해 주세요.':'파일에 확인할 항목이 있습니다. 아래 내용을 확인해 주세요.');
  }catch(e){setError((e as Error).message)}finally{end(updated);setLoading(false)}
 }
 const args={role,effective_from:from,effective_to:to||null,reason,expected_head:overview?.versions.find(v=>v.role===role)?.id??null,batch_id:mode==='excel'?batch:null,rows:mode==='native'?rows:null};
 async function compare(){setError('');setLoading(true);try{setProposal(await api<Proposal>(`/months/${draft.month}/masters/compare`,'POST',args));setMessage('변경 전후와 적용 기간을 확인한 뒤 새 기준 버전으로 저장해 주세요.')}catch(e){setError((e as Error).message)}finally{setLoading(false)}}
 async function publish(){if(!proposal||!begin())return;setLoading(true);setError('');try{const r=await api<{draft:Draft;version_id:string}>(`/months/${draft.month}/masters`,'POST',{...args,expected_revision:draft.revision,fingerprint:proposal.fingerprint});setDirty(false);onDirty(false);setProposal(undefined);end(r.draft);setMode(role==='bom_master'?'excel':'native');await loadVersion(r.version_id);await refresh();setMessage('새 기준 버전을 저장했습니다. 현재 월에 쓰려면 아래에서 적용 전 차이를 확인해 주세요.')}catch(e){setError((e as Error).message);end()}finally{setLoading(false)}}
 async function compareSelection(){setError('');setLoading(true);try{setSelection(await api(`/months/${draft.month}/masters/${version}/comparison`))}catch(e){setError((e as Error).message)}finally{setLoading(false)}}
 async function apply(){if(!selection||selection.version_id!==version||!begin())return;setError('');setLoading(true);try{const d=await api<Draft>(`/months/${draft.month}/masters/select`,'POST',{expected_revision:draft.revision,version_id:version});end(d);setSelection(undefined);setMessage('이번 달 계산 기준에 적용했습니다. 영향을 받는 월별 수정값은 마감 검토에서 다시 확인해 주세요.');await refresh()}catch(e){setError((e as Error).message);end()}finally{setLoading(false)}}
 function update(k:string,v:unknown){setRows(rs=>rs.map((r,i)=>i===index?{...r,[k]:v}:r));changed()}
 function add(){const r:Row=role==='route_master'?{part:'',route_id:crypto.randomUUID().slice(0,8),supplier:'희성',path:'',plant:'',destination:'',state:'설정 완료',note:'',source_role:'product_stock',warehouses:[],metric:'입고/이동처리',included:true}:role==='price_master'?{part:'',price:''}:{part:'',destination:'',price:'',price_kind:'가단가',reason:'',basis:''};setRows(rs=>[...rs,r]);setIndex(rows.length);changed()}
 const row=rows[index];const locked=disabled||loading||Boolean(draft.finalized);const chosen=overview?.versions.find(v=>v.id===overview.selected[role]);
 return <section className="paper master-management" id="master-management" aria-label="프로그램 기준 관리"><div className="section-head"><h2>프로그램 기준 관리</h2><span>원본 엑셀 → 비교·등록 → 프로그램에서 관리</span></div><div className="source-body">
  <ChoiceManagerButton disabled={disabled||loading}/><p>목록에 없는 경로·공장·고객사는 선택 목록 관리에서 추가한 뒤 선택하세요.</p>
  <p>물류 경로·상세 공장·ERP 마감처와 촉매 기본 단가는 여기서 관리합니다. 이번 달 가단가는 마감 검토에서 수정합니다. BOM은 품목별로 화면에서 추가하거나 엑셀 수정본을 가져올 수 있습니다. 등록한 기준은 적용 기간에 맞는 새 월 작업에 이어집니다.</p>
  <div className="master-status-cards" role="group" aria-label="기준 등록·적용 상태">{cardOrder.map(key=>{const state=registrationStatus(key);return <button key={key} type="button" aria-label={labels[key]} aria-pressed={role===key} className={`master-status-card ${role===key?'chosen':''}`} disabled={disabled||loading||dirty||!overview} onClick={()=>chooseRole(key)}><strong>{cardLabels[key]}</strong><span className={`master-status-${state.kind}`}>{state.text}</span><small>{state.detail}</small>{state.pending&&<small className="master-status-warning">{state.pending}</small>}</button>})}</div>
  <p className="hint">카드를 누르면 해당 기준을 관리합니다. ‘이번 달 사용’은 현재 계산 기준으로 적용된 상태이며, 제품별 연결·수량 검산은 마감 검토에서 확인합니다.</p>
  {overviewError&&<button disabled={loading||disabled} onClick={()=>void refresh()}>기준 상태 다시 확인</button>}
  {helpRequest?.target.masterRole===role&&helpRequest.target.part&&<p className="hint">마감 검토에서 확인할 품번: <strong>{helpRequest.target.part}</strong> · {cardLabels[role]} 기준을 확인한 뒤 마감 검토로 돌아가 다시 계산해 주세요.</p>}
  <p className="master-current">이번 달 기준: <strong>{chosen?`${labels[role]} v${chosen.version} · ${chosen.effective_from}부터${chosen.effective_to?` ${chosen.effective_to}까지`:''}`:role==='price_master'?(overview?.candidates.find(b=>b.role==='price_master'&&b.selected)?.filename??'촉매 단가 파일을 먼저 등록하거나 화면에서 입력해 주세요.'):'프로그램 기준 미등록 · 채택한 엑셀 기준 사용'}</strong></p>
  {error&&<p role="alert" className="error">{error}</p>}{message&&<p role="status" className="source-message">{message}</p>}
  {role==='bom_master'&&!bomEntry&&<button disabled={locked||dirty} onClick={()=>{setBomContext(undefined);setBomEntry(true)}}>BOM 품목 추가</button>}
  {role==='bom_master'&&bomEntry&&<BomEntry key={`${draft.id}-${helpRequest?.id??0}`} draft={draft} context={bomContext} disabled={locked} begin={begin} end={end} onDirty={v=>{setDirty(v);onDirty(v);if(v)setMessage('')}} onClose={()=>setBomEntry(false)} onSaved={id=>{setBomEntry(false);setVersion('');setProposal(undefined);setSelection(undefined);void loadVersion(id);setMessage('BOM을 저장하고 이번 달에 적용했습니다. 마감 검토에서 다시 계산해 주세요.')}}/>}
  {role==='bom_master'&&message.includes('BOM을 저장')&&<a href="#review">마감 검토로 돌아가기 →</a>}
  {repairContext&&<MasterRepair key={`${draft.id}-${helpRequest?.id}`} draft={draft} target={repairContext} disabled={disabled||Boolean(draft.finalized)} begin={begin} end={end} onDirty={v=>{setDirty(v);onDirty(v);if(v)setMessage('')}} onClose={()=>setRepairContext(undefined)} onSaved={id=>{setRepairContext(undefined);setProposal(undefined);setSelection(undefined);void loadVersion(id);setMessage('수정한 기준을 저장하고 이번 달에 적용했습니다. 마감 검토에서 다시 계산해 주세요.')}}/>}
  {!bomEntry&&!repairContext&&<>
  <div className="source-controls"><label>선택한 기준<input aria-label="선택한 기준" readOnly value={labels[role]}/></label>
  <label>저장된 기준 버전<select value={version} disabled={dirty||loading} onChange={e=>{if(e.target.value)void loadVersion(e.target.value)}}><option value="">버전 선택</option>{overview?.versions.filter(v=>v.role===role).map(v=><option key={v.id} value={v.id}>v{v.version} · {v.effective_from}~{v.effective_to??'계속'} · {v.reason}</option>)}</select></label>
  {version&&<a href={`/api/masters/${version}/export`}>검토용 엑셀 내려받기</a>}</div>
  <div className="master-file-register"><h3>{labels[role]} 파일 등록</h3><div className="source-controls"><label>기준 파일<input key={role} ref={fileInputRef} aria-label="기준 파일" type="file" accept=".xlsx" disabled={locked} onChange={e=>{setFile(e.target.files?.[0]);setFileResult(undefined);changed()}}/></label><button className="primary" disabled={locked||!file} onClick={()=>void registerFile()}>기준 파일 읽기</button></div><p className="hint">파일을 읽고 아래에서 변경 내용을 비교·저장한 뒤 이번 달에 적용합니다. 적용 시작월·종료월을 지정하면 새 월에도 해당 기준을 사용합니다.</p>{fileResult&&<div><strong>{fileResult.filename} · {fileResult.status==='ready'?'읽기 검산 완료':'확인 필요'}</strong>{fileResult.result.summary.row_count!==undefined&&<p>원문 {fileResult.result.summary.row_count}행 · 품번 {fileResult.result.summary.part_count}종</p>}<a href={`/api/months/${draft.month}/sources/${fileResult.id}/original`}>보관 원본 다운로드</a>{fileResult.result.issues.map((i,n)=><p className="error" key={n}>{i.location} — {i.message}</p>)}</div>}<details><summary>등록한 기준 파일 {overview?.candidates.filter(c=>c.role===role).length??0}개</summary><div className="table-wrap"><table><thead><tr><th>파일</th><th>읽기 상태</th><th>내용</th><th>원본</th></tr></thead><tbody>{overview?.candidates.filter(c=>c.role===role).map(c=><tr key={c.id}><td>{c.filename}</td><td>{c.status==='ready'?'읽기 검산 완료':'확인 필요'}</td><td><button disabled={locked||dirty} onClick={()=>void inspectFile(c.id)}>읽기 결과 보기</button></td><td><a href={`/api/months/${draft.month}/sources/${c.id}/original`}>원본 다운로드</a></td></tr>)}</tbody></table></div></details></div>
  <div className="master-apply"><button disabled={locked||dirty||!version||chosen?.id===version} onClick={()=>void compareSelection()}>이번 달 적용 전 차이 보기</button>{selection&&<><Changes changes={selection.changes}/><button className="primary" disabled={locked||dirty} onClick={()=>void apply()}>이 버전을 이번 달에 적용</button></>}</div>
  {role==='price_master'&&<p className="hint">품번별 기본 단가를 조회·수정합니다. 변경 사유를 입력하고 비교 → 새 버전 저장 → 이번 달 적용 순서로 반영합니다. 이번 달 가단가·마감처별 예외는 마감 검토 → 촉매 선택 → 단가에서 수정합니다.</p>}
  <fieldset disabled={locked} className="master-fieldset"><legend>새 기준 버전 작성</legend>
  <div className="source-controls"><label>작성 방법<select value={mode} disabled={dirty} onChange={e=>{setMode(e.target.value);setProposal(undefined)}}>{role!=='bom_master'&&<option value="native">화면에서 수정</option>}{role!=='price_policy'&&<option value="excel">등록한 엑셀에서 가져오기</option>}</select></label>
  {mode==='excel'&&<label>등록한 엑셀 후보<select value={batch} onChange={e=>{setBatch(e.target.value);changed()}}><option value="">이 화면에서 기준 파일을 선택해 주세요</option>{overview?.candidates.filter(b=>b.role===role&&b.status==='ready').map(b=><option key={b.id} value={b.id}>{b.filename}</option>)}</select></label>}
  <label>적용 시작월<input type="month" value={from} onChange={e=>{setFrom(e.target.value);changed()}}/></label><label>적용 종료월 (선택)<input type="month" value={to} onChange={e=>{setTo(e.target.value);changed()}}/></label></div>
  {mode==='native'&&role!=='bom_master'&&<><div className="source-controls"><label>기준 품번·경로 검색<input value={query} onChange={e=>setQuery(e.target.value)}/></label><button onClick={add}>기준 행 추가</button><span>{rows.length}행</span></div><div className="master-grid"><div className="master-list">{rows.map((r,i):Row&{i:number}=>({...r,i})).filter(r=>JSON.stringify(r).toLowerCase().includes(query.toLowerCase())).map(r=><button key={r.i} className={r.i===index?'selected':''} onClick={()=>setIndex(r.i)}><strong>{r.part||'새 품번 입력'}</strong><span>{String(r.path??r.price_kind??(role==='price_master'?`${r.price}원`:''))} · {String(r.plant??r.destination??'')}</span><small>{String(r.destination??'')}</small></button>)}</div><div className="master-editor">{row?<><h3>{row.part||'새 기준'} 상세</h3><div className="master-fields">{(role==='route_master'?['part','route_id','supplier','path','plant','destination','state','note']:role==='price_master'?['part','price']:['part','destination','price','price_kind','reason','basis']).map(k=><label key={k}>{fieldNames[k]}{k==='supplier'?<SupplierSelect value={String(row[k]??'')} onChange={v=>update(k,v)}/>:k==='destination'?<DestinationSelect value={String(row[k]??'')} onChange={v=>update(k,v)}/>:k==='path'||k==='plant'?<ChoiceSelect category={k} value={String(row[k]??'')} onChange={v=>update(k,v)}/>:k==='state'?<StateSelect value={String(row[k]??'')} onChange={v=>update(k,v)}/>:k==='note'?<textarea value={String(row[k]??'')} onChange={e=>update(k,e.target.value)}/>:k==='price_kind'?<select value={String(row[k])} onChange={e=>update(k,e.target.value)}><option>가단가</option><option>정단가</option></select>:<input value={String(row[k]??'')} onChange={e=>update(k,e.target.value)}/>}</label>)}
  {role==='route_master'&&<><label>집계 자료<select value={String(row.source_role??'')} onChange={e=>update('source_role',e.target.value)}><option value="">확인 필요</option><option value="product_stock">제품 수불</option><option value="semi_stock">반제품 수불</option><option value="glovis_receipts">글로비스 실제 입고</option></select></label><label>집계 창고<WarehouseSelect value={row.warehouses as string[]??[]} onChange={v=>update('warehouses',v)}/></label><label>수량 항목<select value={String(row.metric??'')} onChange={e=>update('metric',e.target.value)}>{['','입고/이동처리','출고/적송처리','출고/이동처리','입고/기타입고','실제 입고수량'].map(m=><option key={m} value={m}>{m||'확인 필요'}</option>)}</select></label><label className="master-check"><input type="checkbox" checked={row.included!==false} onChange={e=>update('included',e.target.checked)}/>배분에 집계 (해제하면 이동 추적용)</label></>}</div><button onClick={()=>{setRows(rs=>rs.filter((_,i)=>i!==index));setIndex(0);changed()}}>새 버전에서 이 행 제외</button></>:<p>저장된 버전을 선택하거나 기준 행을 추가해 주세요. 처음에는 해당 기준 파일을 등록하거나 화면에서 행을 추가해 주세요.</p>}</div></div></>}
  <label className="master-reason">기준 변경 사유<input value={reason} maxLength={1000} onChange={e=>{setReason(e.target.value);changed()}}/></label>
  <div className="source-controls"><button disabled={!reason.trim()||(mode==='excel'&&!batch)} onClick={()=>void compare()}>기준 변경 내용 비교</button><button onClick={discard}>기준 편집 취소</button><span>{dirty?'입력 중 · 아직 저장하지 않음':'버전 저장과 이번 달 적용은 별도로 진행합니다.'}</span></div>
  {proposal&&<><Changes changes={proposal.changes}/><button className="primary" onClick={()=>void publish()}>새 기준 버전 저장</button></>}
  </fieldset>
  <section className="master-reset-box" aria-label="선택한 기준 자료 초기화"><h3>선택한 기준 자료 초기화</h3><p>{cardLabels[role]}의 등록 버전과 파일을 비우고 처음부터 다시 등록합니다. 다른 기준·월계획·실적은 유지합니다.</p><button disabled={locked||dirty} onClick={()=>void previewReset()}>{cardLabels[role]} 초기화 범위 확인</button>{resetPreview?.role===role&&<div className="master-reset-confirm"><p><strong>이 자료 폴더의 {resetPreview.label}: 버전 {resetPreview.version_count}개 · 등록 파일 {resetPreview.source_count}건 · 보관 원본 {resetPreview.file_count}개</strong></p><p>초기화하면 이번 달 적용도 해제됩니다. 프로그램에서 되돌릴 수 없으며, 다시 사용하려면 기준을 새로 등록해야 합니다. 다른 자료와 공유하는 보관 원본은 유지합니다.</p>{resetPreview.blocked.length>0?<div role="alert"><strong>사용 중인 기준이 있어 초기화할 수 없습니다.</strong>{resetPreview.blocked.map(x=><p key={x}>{x}</p>)}</div>:resetPreview.version_count+resetPreview.source_count===0?<p>초기화할 등록 자료가 없습니다.</p>:<><label className="master-check"><input type="checkbox" checked={resetConfirmed} disabled={locked} onChange={e=>setResetConfirmed(e.target.checked)}/>{resetPreview.label}의 등록 버전·파일을 비우는 것을 확인했습니다.</label><button className="danger" disabled={locked||dirty||!resetConfirmed} onClick={()=>void resetMaster()}>확인한 기준 초기화 실행</button></>}<button disabled={loading} onClick={()=>{setResetPreview(undefined);setResetConfirmed(false)}}>취소</button></div>}</section>
 </>}
 </div></section>
}

export function MonthReset({draft,disabled,begin,end}:Omit<Props,'onDirty'>){
 const [open,setOpen]=useState(false);const [reason,setReason]=useState('');const [error,setError]=useState('');const [archives,setArchives]=useState<{id:string;note:string;updated_at:string}[]>([]);
 useEffect(()=>{api<typeof archives>(`/months/${draft.month}/archives`).then(setArchives).catch(e=>setError(e.message))},[draft.id,draft.revision]);
 async function reset(){if(!begin())return;setError('');try{const d=await api<Draft>(`/months/${draft.month}/reset`,'POST',{expected_revision:draft.revision,reason});setReason('');setOpen(false);end(d)}catch(e){setError((e as Error).message);end()}}
 return <section className="paper month-reset" aria-label="월 작업 초기화"><div className="section-head"><h2>월 작업 초기화</h2><button disabled={disabled||draft.finalized} onClick={()=>setOpen(!open)}>이 월의 입력 다시 시작</button></div><div className="source-body"><p>입력한 이월 수정·보류·공장 배분·단가 수정·작업 메모를 비운 새 초안을 만듭니다. BOM·경로·촉매 단가와 기존 단가 기준·다른 등록 원본은 유지합니다. 월계획과 엑셀 배분 입력은 이번 달 사용을 해제하며 파일은 보존합니다. 전월 확정 이월 연결·과거 확정본도 보존합니다.</p>{draft.finalized&&<p>확정 월은 먼저 ‘새 확정 버전 작업 시작’을 선택해 주세요.</p>}{error&&<p role="alert" className="error">{error}</p>}{open&&<div className="reset-confirm"><strong>{draft.month}의 현재 초안은 보관 이력으로 남습니다.</strong><label>초기화 사유<input value={reason} maxLength={1000} onChange={e=>setReason(e.target.value)}/></label><button disabled={disabled||!reason.trim()} onClick={()=>void reset()}>이전 초안을 보관하고 초기화</button><button disabled={disabled} onClick={()=>setOpen(false)}>취소</button></div>}<details><summary>초기화로 보관한 초안 {archives.length}건</summary>{archives.map(a=><p key={a.id}>{new Date(a.updated_at).toLocaleString('ko-KR')} · {a.note||'메모 없음'}</p>)}</details></div></section>
}
