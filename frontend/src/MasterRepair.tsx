import {ChoiceSelect,DestinationSelect,StateSelect,WarehouseSelect} from './Choices';
import {useEffect,useRef,useState} from 'react';
import {api,type Draft} from './api';
import {SupplierSelect} from './PartnerSelect';
import type {HelpTarget} from './IssueHelp';
type Row={part:string;[key:string]:unknown};
type Base={revision:number;expected_head:string|null;rows:Row[];products:string[]};
type Props={draft:Draft;target:HelpTarget;disabled:boolean;onDirty:(v:boolean)=>void;begin:()=>boolean;end:(d?:Draft)=>void;onClose:()=>void;onSaved:(id:string)=>void};
const fields:Record<string,string>={part:'제품 품번',supplier:'촉매사',path:'납품 경로',plant:'상세 마감공장',destination:'ERP 마감처',state:'처리 상태',note:'비고'};
export function MasterRepair({draft,target,disabled,onDirty,begin,end,onClose,onSaved}:Props){
 const pricing=target.masterRole==='price_master';
 const [base,setBase]=useState<Base>();const [form,setForm]=useState<Row>();const [pick,setPick]=useState('');
 const [edited,setEdited]=useState(false);const [reason,setReason]=useState('');const [error,setError]=useState('');const [busy,setBusy]=useState(false);const panel=useRef<HTMLFieldSetElement>(null);
 const targetPart=target.part&&target.part!=='*'?target.part:'';
 function blank(product:string):Row{return pricing?{part:targetPart,price:''}:{part:product,route_id:crypto.randomUUID().slice(0,8),supplier:target.supplier??'',path:'',plant:'',destination:'',state:'설정 완료',note:'',source_role:'',warehouses:[],metric:'',included:true}}
 function candidates(b:Base){return b.rows.map((row,index)=>({row,index})).filter(({row})=>pricing?row.part===targetPart:b.products.includes(row.part))}
 useEffect(()=>{let active=true;
  api<Base>(`/months/${draft.month}/masters/editor?${new URLSearchParams({role:target.masterRole!,part:targetPart,part_kind:target.partKind??'catalyst'})}`).then(b=>{
   if(!active)return;setBase(b);const found=candidates(b);
   if(pricing){const prices=new Set(found.map(x=>x.row.price));setForm({part:targetPart,price:prices.size===1?found[0].row.price:''})}
   else if(found.length===1){setPick(String(found[0].index));setForm({...found[0].row})}
   else if(!found.length&&b.products.length<=1){setPick('new');setForm(blank(b.products[0]??''))}
  }).catch(e=>{if(active)setError(e.message)});
  panel.current?.scrollIntoView({block:'start'});return()=>{active=false};
 },[draft.id,target]);
 useEffect(()=>{requestAnimationFrame(()=>{panel.current?.scrollIntoView({block:'start'});panel.current?.querySelector<HTMLInputElement>('input:not([readonly])')?.focus({preventScroll:true})})},[Boolean(form),pick]);
 function update(key:string,v:unknown){setForm(f=>f?{...f,[key]:v}:f);setEdited(true);onDirty(true);setError('')}
 function choose(v:string){setPick(v);setForm(v==='new'?blank(base?.products.length===1?base.products[0]:''):v?{...base!.rows[Number(v)]}:undefined)}
 async function save(){
  if(!base||!form||!begin())return;setBusy(true);setError('');let updated:Draft|undefined;
  try{
   const rows=pricing?[...base.rows.filter(r=>r.part!==targetPart),form]:pick==='new'?[...base.rows,form]:base.rows.map((r,i)=>i===Number(pick)?form:r);
   const args={role:target.masterRole,effective_from:draft.month,effective_to:null,reason,expected_head:base.expected_head,rows};
   const p=await api<{fingerprint:string}>(`/months/${draft.month}/masters/compare`,'POST',args);
   const r=await api<{draft:Draft;version_id:string}>(`/months/${draft.month}/masters/save-apply`,'POST',{...args,expected_revision:base.revision,fingerprint:p.fingerprint});
   updated=r.draft;onDirty(false);onSaved(r.version_id);
  }catch(e){setError((e as Error).message)}finally{end(updated);setBusy(false)}
 }
 const locked=disabled||busy||Boolean(draft.finalized);const found=base?candidates(base):[];
 return <fieldset ref={panel} className="master-fieldset" aria-label={pricing?'이 품목의 기본 단가 수정':'이 품목의 경로 수정'} disabled={locked}><legend>{pricing?'이 품목의 기본 단가 수정':'이 품목의 경로 수정'}</legend>
 <p>확인할 {target.partKind==='product'?'제품':'촉매'}: <strong>{targetPart}</strong> · {draft.month} 기준</p>
 {!base&&!error&&<p>이번 달 기준을 불러오고 있습니다…</p>}
 {!pricing&&base&&<><p>연결된 제품: {base.products.join(', ')||'BOM에서 연결된 제품을 찾지 못했습니다. 제품 품번을 직접 확인해 입력해 주세요.'}</p><label className="master-reason">수정할 경로<select aria-label="수정할 경로" disabled={edited} value={pick} onChange={e=>choose(e.target.value)}><option value="">경로를 선택하세요</option>{found.map(({row,index})=><option key={index} value={index}>{row.part} · {String(row.path)} · {String(row.plant)} · {String(row.destination)}</option>)}<option value="new">새 경로 추가</option></select></label>{found.length>1&&<p>여러 경로가 있습니다. 수정할 경로를 선택하면 기존 값이 채워집니다.</p>}</>}
 {pricing&&found.length>1&&<p>등록된 단가가 여러 개입니다: {found.map(x=>String(x.row.price)).join(', ')}원. 저장하면 이 품번의 기본 단가를 입력한 값으로 통일합니다.</p>}
 {form&&<><div className="master-fields">
 {pricing?<><label>촉매 품번<input readOnly value={form.part}/></label><label>기본 단가<input aria-label="기본 단가" inputMode="decimal" value={String(form.price??'')} onChange={e=>update('price',e.target.value)}/></label></>:<>
 {Object.entries(fields).map(([k,label])=><label key={k}>{label}{k==='supplier'?<SupplierSelect value={String(form.supplier??'')} onChange={v=>update('supplier',v)}/>:k==='path'||k==='plant'?<ChoiceSelect category={k} value={String(form[k]??'')} onChange={v=>update(k,v)}/>:k==='destination'?<DestinationSelect value={String(form[k]??'')} onChange={v=>update(k,v)}/>:k==='state'?<StateSelect value={String(form[k]??'')} onChange={v=>update(k,v)}/>:<input aria-label={label} list={k==='part'?'repair-products':undefined} value={String(form[k]??'')} onChange={e=>update(k,e.target.value)}/>}</label>)}
 <datalist id="repair-products">{base?.products.map(p=><option key={p} value={p}/>)}</datalist>
 <label>집계 자료<select aria-label="집계 자료" value={String(form.source_role??'')} onChange={e=>update('source_role',e.target.value)}><option value="">선택하세요</option><option value="product_stock">제품 수불</option><option value="semi_stock">반제품 수불</option><option value="glovis_receipts">글로비스 실제 입고</option></select></label>
 <label>집계 창고<WarehouseSelect value={form.warehouses as string[]??[]} onChange={v=>update('warehouses',v)}/></label>
 <label>수량 항목<select aria-label="수량 항목" value={String(form.metric??'')} onChange={e=>update('metric',e.target.value)}>{['','입고/이동처리','출고/적송처리','출고/이동처리','입고/기타입고','실제 입고수량'].map(v=><option key={v} value={v}>{v||'선택하세요'}</option>)}</select></label>
 <label className="master-check"><input type="checkbox" checked={form.included!==false} onChange={e=>update('included',e.target.checked)}/>배분에 집계</label></>}
 </div><label className="master-reason">변경 사유<input aria-label="변경 사유" value={reason} maxLength={1000} onChange={e=>{setReason(e.target.value);setEdited(true);onDirty(true)}}/></label>
 <p className="hint">다른 품목은 유지합니다. 저장하면 새 기준 버전으로 만들고 이번 달에 바로 적용합니다.</p>
 <button className="primary" disabled={locked||!reason.trim()||!form.part.trim()||(pricing&&!String(form.price??'').trim())} onClick={()=>void save()}>수정 저장·이번 달 적용</button>{' '}</>}
 <button onClick={()=>{onDirty(false);onClose()}}>수정 화면 닫기</button>{error&&<p className="error" role="alert">{error}</p>}
 </fieldset>;
}
