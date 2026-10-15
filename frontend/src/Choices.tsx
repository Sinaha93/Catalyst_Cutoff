import {createContext,useContext,useEffect,useRef,useState,type ReactNode} from 'react';
import {api} from './api';
import './choices.css';

export type Category='customer'|'path'|'plant'|'destination'|'warehouse';
type Item={name:string;active:boolean;origin:string};
type Data={revision:number;categories:Record<Category,Item[]>};
const labels:Record<Category,string>={customer:'BOM 고객사',path:'납품 경로',plant:'상세 마감공장',destination:'ERP 마감처',warehouse:'집계 창고'};
const Context=createContext<{data?:Data;open:(category?:Category)=>void}>({open:()=>{}});
export function ChoicesProvider({children,enabled,refreshKey}:{children:ReactNode;enabled:boolean;refreshKey:string}){
 const [data,setData]=useState<Data>();const [category,setCategory]=useState<Category>('path');const [opened,setOpened]=useState(false);
 const [name,setName]=useState('');const [query,setQuery]=useState('');const [error,setError]=useState('');const [busy,setBusy]=useState(false);const [message,setMessage]=useState('');
 const dialog=useRef<HTMLDialogElement>(null);const serial=useRef(0);
 async function refresh(){const seq=++serial.current;try{const d=await api<Data>('/choices');if(seq===serial.current){setData(d);setError('')}}catch(e){if(seq===serial.current)setError((e as Error).message)}}
 useEffect(()=>{if(enabled)void refresh()},[enabled,refreshKey]);
 useEffect(()=>{if(opened)dialog.current?.showModal();else dialog.current?.close()},[opened]);
 async function save(value:string,active:boolean){if(!data)return;setBusy(true);setError('');++serial.current;
  try{setData(await api<Data>('/choices','POST',{category,name:value,active,expected_revision:data.revision}));setName('');setMessage(`${value}: ${active?'사용 목록에 반영했습니다.':'새 선택에서 제외했습니다. 기존 기준은 유지됩니다.'}`)}catch(e){setError((e as Error).message)}finally{setBusy(false)}
 }
 function open(c?:Category){if(c)setCategory(c);setName('');setQuery('');setMessage('');setOpened(true);void refresh()}
 return <Context.Provider value={{data,open}}>{children}<dialog ref={dialog} className="choices-dialog" aria-label="선택 목록 관리" onCancel={e=>{if(busy)e.preventDefault();else setOpened(false)}} onClose={()=>setOpened(false)}>
 <div className="section-head"><h2>선택 목록 관리</h2><button disabled={busy} onClick={()=>setOpened(false)}>닫기</button></div>
 <p>목록은 이 PC의 자료 폴더에서 모든 월이 함께 사용합니다. 이름을 추가해도 제품의 경로가 자동으로 연결되지는 않습니다.</p>
 <p className="hint">오타는 올바른 이름을 추가하고 잘못된 이름을 ‘사용 중지’하세요. 이미 저장한 BOM·경로·과거 마감 결과는 바뀌지 않습니다. 해당 기준은 별도로 수정해 주세요.</p>
 <div className="source-controls"><label>관리할 목록<select value={category} disabled={busy} onChange={e=>{setCategory(e.target.value as Category);setName('');setQuery('');setMessage('')}}>{Object.entries(labels).map(([k,v])=><option key={k} value={k}>{v}</option>)}</select></label><button disabled={busy} onClick={()=>void refresh()}>목록 새로 읽기</button></div>
 <div className="source-controls"><label>새 이름<input value={name} maxLength={200} disabled={busy} onChange={e=>setName(e.target.value)}/></label><button className="primary" disabled={busy||!data||!name.trim()} onClick={()=>void save(name,true)}>목록에 추가</button></div>
 {message&&<p role="status">{message}</p>}{error&&<p className="error" role="alert">{error}</p>}
 <label>이름 찾기<input value={query} onChange={e=>setQuery(e.target.value)}/></label>
 <div className="choices-list"><table><thead><tr><th>이름</th><th>가져온 곳</th><th>상태</th><th>관리</th></tr></thead><tbody>{data?.categories[category].filter(x=>x.name.includes(query)).map(x=><tr key={x.name}><td>{x.name}</td><td>{x.origin}</td><td>{x.active?'사용':'사용 중지'}</td><td><button disabled={busy} onClick={()=>void save(x.name,!x.active)}>{x.active?'사용 중지':'다시 사용'}</button></td></tr>)}</tbody></table>{!data&&<p>목록을 읽고 있습니다.</p>}</div>
 <p className="hint">촉매사는 지원하는 희성·유미코아 중에서 선택합니다. 집계 자료·수량 항목·처리 상태는 계산 규칙에 맞는 고정 목록입니다.</p>
 </dialog></Context.Provider>;
}
export function ChoiceManagerButton({category,disabled=false}:{category?:Category;disabled?:boolean}){const {open}=useContext(Context);return <button type="button" disabled={disabled} onClick={()=>open(category)}>선택 목록 관리</button>}
export function ChoiceSelect({category,value,onChange,label,exclude=[],empty='선택하세요'}:{category:Category;value:string;onChange:(v:string)=>void;label?:string;exclude?:string[];empty?:string}){
 const {data,open}=useContext(Context);const items=data?.categories[category]??[];const current=items.find(x=>x.name===value);
 return <span className="choice-control"><select aria-label={label??labels[category]} value={value} onChange={e=>onChange(e.target.value)}><option value="">{empty}</option>{value&&(!current||!current.active)&&<option value={value} disabled>{value} · {current?'사용 중지 · 기존 값':'기존 값'}</option>}{items.filter(x=>x.active).map(x=><option key={x.name} value={x.name} disabled={exclude.includes(x.name)&&x.name!==value}>{x.name}</option>)}</select><button type="button" className="choice-manage" aria-label={`${labels[category]} 목록 관리`} onClick={()=>open(category)}>목록 관리</button></span>;
}
export function WarehouseSelect({value,onChange}:{value:string[];onChange:(v:string[])=>void}){
 return <span className="warehouse-choices">{value.map((v,i)=><span className="choice-control" key={i}><ChoiceSelect category="warehouse" label={`집계 창고 ${i+1}`} value={v} exclude={value} onChange={x=>onChange(value.map((old,j)=>j===i?x:old))}/><button type="button" onClick={()=>onChange(value.filter((_,j)=>i!==j))}>제외</button></span>)}<button type="button" onClick={()=>onChange([...value,''])}>+ 집계 창고 추가</button></span>;
}
export function DestinationSelect({value,onChange}:{value:string;onChange:(v:string)=>void}){
 const mapped=value.includes(':');const pairs=mapped?value.split('\n').map(line=>{const i=line.indexOf(':');return [line.slice(0,i),line.slice(i+1)]}):[];
 function update(index:number,col:number,v:string){onChange(pairs.map((p,i)=>p.map((x,j)=>i===index&&j===col?v:x).join(':')).join('\n'))}
 return <span className="warehouse-choices"><select aria-label="마감처 지정 방식" value={mapped?'mapped':'single'} onChange={e=>onChange(e.target.value==='mapped'?`:${value}`:pairs[0]?.[1]??'')}><option value="single">공통 마감처</option><option value="mapped">촉매별로 다른 마감처</option></select>{mapped?pairs.map((p,i)=><span className="choice-control" key={i}><input aria-label={`마감처 연결 촉매 ${i+1}`} placeholder="촉매 품번" value={p[0]} onChange={e=>update(i,0,e.target.value.toUpperCase())}/><ChoiceSelect category="destination" value={p[1]} onChange={v=>update(i,1,v)}/>{pairs.length>1&&<button type="button" onClick={()=>onChange(pairs.filter((_,j)=>j!==i).map(p=>p.join(':')).join('\n'))}>제외</button>}</span>):<ChoiceSelect category="destination" value={value} onChange={onChange}/ >}{mapped&&<button type="button" onClick={()=>onChange(value+'\n:')}>+ 촉매별 마감처 추가</button>}</span>;
}
export function StateSelect({value,onChange}:{value:string;onChange:(v:string)=>void}){
 const options=['설정 완료','확인 필요','경로 설정 완료','BOM 기준 등록 완료','설정 완료 / 단산 경로','단산 / 이력 보존'];
 return <select aria-label="처리 상태" value={value} onChange={e=>onChange(e.target.value)}><option value="">선택하세요</option>{value&&!options.includes(value)&&<option value={value}>{value} · 기존 상태</option>}{options.map(x=><option key={x}>{x}</option>)}</select>;
}
