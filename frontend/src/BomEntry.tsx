import {ChoiceSelect} from './Choices';
import {useEffect,useRef,useState} from 'react';
import {api,type Draft} from './api';
import {SupplierSelect,supplierName} from './PartnerSelect';
import type {HelpTarget} from './IssueHelp';

type Row={part:string;supplier:string;customer:string;components:{part:string;usage:string}[]};
type Entry={id:string;product:string;usage:string;customers:string[]};
type Base={revision:number;rows:Row[];customers:string[]};
type Props={draft:Draft;context?:HelpTarget;disabled:boolean;onDirty:(v:boolean)=>void;begin:()=>boolean;end:(d?:Draft)=>void;onClose:()=>void;onSaved:(id:string)=>void};
const empty=(product=''):Entry=>({id:crypto.randomUUID(),product,usage:'',customers:['']});
export function BomEntry({draft,context,disabled,onDirty,begin,end,onClose,onSaved}:Props){
 const [entries,setEntries]=useState<Entry[]>([empty(context?.partKind==='product'?context.part??'':'')]);
 const [catalyst,setCatalyst]=useState(context?.partKind==='catalyst'?context.part??'':'');
 const [supplier,setSupplier]=useState(supplierName(context?.supplier??''));
 const [base,setBase]=useState<Base>();const [error,setError]=useState('');const [busy,setBusy]=useState(false);
 const panel=useRef<HTMLFieldSetElement>(null);
 useEffect(()=>{let active=true;api<Base>(`/months/${draft.month}/masters/bom-entry`).then(x=>{if(active)setBase(x)}).catch(e=>{if(active)setError(e.message)});panel.current?.scrollIntoView({block:'start'});return()=>{active=false}},[draft.id,draft.revision]);
 const locked=disabled||busy||Boolean(draft.finalized);
 function changed(){onDirty(true);setError('')}
 function update(id:string,patch:Partial<Entry>){setEntries(es=>es.map(e=>e.id===id?{...e,...patch}:e));changed()}
 const duplicates=entries.some((e,i)=>e.product.trim()&&entries.slice(0,i).some(x=>x.product.trim().toUpperCase()===e.product.trim().toUpperCase()));
 const incomplete=entries.some(e=>!e.product.trim()||!e.usage.trim()||(e.customers.length>1&&e.customers.some(c=>!c))||new Set(e.customers).size!==e.customers.length);
 async function save(){
  if(!base||!begin())return;
  setBusy(true);setError('');let updated:Draft|undefined;
  try{const result=await api<{draft:Draft;version_id:string}>(`/months/${draft.month}/masters/bom-products`,'POST',{expected_revision:base.revision,catalyst,supplier,products:entries.map(e=>({product:e.product,usage:e.usage,customers:e.customers.filter(Boolean)}))});updated=result.draft;onDirty(false);onSaved(result.version_id)}catch(e){setError((e as Error).message)}finally{end(updated);setBusy(false)}
 }
 return <fieldset ref={panel} className="master-fieldset bom-entry" disabled={locked} aria-label="BOM 품목 추가"><legend>BOM 품목 추가</legend>
 <p>같은 촉매가 들어가는 제품을 모두 추가하세요. 제품마다 소요량과 고객사를 지정하고 <strong>한 번에 저장·이번 달 적용</strong>합니다.</p>
 <div className="master-fields">
 <label>촉매 품번<input value={catalyst} onChange={e=>{setCatalyst(e.target.value);changed()}} maxLength={100}/></label>
 <label>촉매사<SupplierSelect value={supplier} onChange={v=>{setSupplier(v);changed()}}/></label>
 </div>
 {entries.map((entry,index)=>{const matches=base?.rows.filter(r=>r.part===entry.product.trim().toUpperCase())??[];const existing=matches[0];const knownCustomers=Array.from(new Set(matches.map(r=>r.customer).filter(Boolean)));return <fieldset key={entry.id} className="bom-product-entry master-fieldset" aria-label={`제품 연결 ${index+1}`}><legend>제품 {index+1}</legend>
 <div className="master-fields"><label>제품 품번<input value={entry.product} onChange={e=>update(entry.id,{product:e.target.value})} placeholder="실제 제품 품번을 입력하세요" maxLength={100}/></label>
 <label>제품 1개당 촉매 소요량<input inputMode="decimal" value={entry.usage} onChange={e=>update(entry.id,{usage:e.target.value})} placeholder="예: 제품 1개에 촉매 1개면 1" maxLength={50}/></label></div>
 {existing&&<div className="master-current"><strong>등록된 제품에 촉매를 추가합니다.</strong><p>기존 구성: {existing.components.map(c=>`${c.part} × ${c.usage}`).join(', ')||'없음'}</p><p>기존 고객사: {knownCustomers.join(', ')||'미지정'} · 기존 구성과 고객사는 유지합니다.</p></div>}
 <div className="bom-customer-list">{entry.customers.map((customer,ci)=><div className="source-controls" key={ci}><label>고객사 (선택)<ChoiceSelect category="customer" label="고객사 (선택)" value={customer} exclude={[...knownCustomers,...entry.customers.filter(c=>c!==customer)]} empty={existing?'기존 고객사 유지':'미지정'} onChange={v=>update(entry.id,{customers:entry.customers.map((c,i)=>i===ci?v:c)})}/></label>{entry.customers.length>1&&<button type="button" onClick={()=>update(entry.id,{customers:entry.customers.filter((_,i)=>i!==ci)})}>고객사 선택 삭제</button>}</div>)}</div>
 <div className="source-controls"><button type="button" disabled={entry.customers.length>=100} onClick={()=>update(entry.id,{customers:[...entry.customers,'']})}>+ 고객사 추가</button>{entries.length>1&&<button type="button" onClick={()=>{setEntries(es=>es.filter(e=>e.id!==entry.id));changed()}}>이 제품 입력 삭제</button>}</div>
 <p className="hint">고객사가 여러 곳이어도 이 제품의 촉매 소요량은 동일하게 적용합니다. 고객사를 추가하면 같은 구성의 BOM 행이 추가되며 계산할 때 중복 합산하지 않습니다.</p>
 </fieldset>})}
 <button type="button" disabled={entries.length>=100} onClick={()=>{const added=empty();setEntries(es=>[...es,added]);changed();requestAnimationFrame(()=>{const panels=panel.current?.querySelectorAll<HTMLElement>('.bom-product-entry');const last=panels?.[panels.length-1];last?.scrollIntoView({block:'start'});last?.querySelector<HTMLInputElement>('input')?.focus({preventScroll:true})})}}>+ 제품 추가</button>
 <p className="hint">새 고객사는 옆의 목록 관리에서 추가한 뒤 선택하세요. 납품 공장과 수량 배분은 경로·공장 기준에서 연결합니다.</p>
 {duplicates&&<p className="error">같은 제품은 한 번만 입력하고, 해당 제품 안에서 고객사를 추가해 주세요.</p>}
 {entries.some(e=>e.customers.length>1&&e.customers.some(c=>!c))&&<p className="hint">추가한 고객사를 모두 선택하거나 빈 선택란을 삭제해 주세요.</p>}
 {error&&<p role="alert" className="error">{error}</p>}
 <div className="source-controls"><button className="primary" disabled={locked||!base||!catalyst.trim()||!supplier||incomplete||duplicates} onClick={()=>void save()}>BOM 저장·이번 달 적용</button><button type="button" disabled={locked} onClick={()=>{onDirty(false);onClose()}}>품목 추가 취소</button><span>제품 {entries.length}종을 함께 검증·저장합니다.</span></div>
 </fieldset>;
}
