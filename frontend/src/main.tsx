import {Masters,MonthReset} from './Masters';
import {Closing} from './Closing';
import {Workflow,type ReviewProgress,type SourceProgress} from './Workflow';
import {pages,mainMenu,reviewMenu,pageFromHash,type Page} from './navigation';
import {Holds} from './Holds';
import {Reconciliation} from './Reconciliation';
import {Allocation} from './Allocation';
import {Pricing} from './Pricing';
import {Basis} from './Basis';
import {useEffect, useRef, useState} from 'react';
import {createRoot} from 'react-dom/client';
import {api, setToken, type Draft, type Session, type History} from './api';
import './style.css';
import './workflow.css';
import {Sources} from './Sources';
import {Guide} from './Guide';

function initialMonth() {const d = new Date(); d.setMonth(d.getMonth() - 1, 1); return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`}
const monthLabel = (m: string) => `${m.slice(0, 4)}년 ${Number(m.slice(5))}월`;
const timeLabel = (s: string) => new Date(s).toLocaleString('ko-KR', {month:'2-digit', day:'2-digit', hour:'2-digit', minute:'2-digit', second:'2-digit'});

function App() {
  const [page,setPage]=useState<Page>(pageFromHash);
  const [reviewProgress,setReviewProgress]=useState<ReviewProgress>();
  const [sourceProgress,setSourceProgress]=useState<SourceProgress>();
  const [evidencePage,setEvidencePage]=useState('reconciliation');
  const [navigationMessage,setNavigationMessage]=useState('');
  const [session, setSession] = useState<Session>();
  const [months, setMonths] = useState<Draft[]>([]);
  const [listMessage,setListMessage]=useState('');
  const [draft, setDraft] = useState<Draft>();
  const [note, setNote] = useState('');
  const [month, setMonth] = useState(initialMonth);
  const [history, setHistory] = useState<History[]>([]);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [loadFailed, setLoadFailed] = useState(false);
  const [reading, setReading] = useState(false);
  const [sourceFormDirty, setSourceDirty] = useState(false);
  const [holdDirty, setHoldDirty] = useState(false);
  const [closingDirty, setClosingDirty] = useState(false);
  const [masterDirty, setMasterDirty] = useState(false);
  const sourceDirty = sourceFormDirty || holdDirty || closingDirty || masterDirty;
  const [stopped, setStopped] = useState(false);
  const lock = useRef(false);
  const dirty = Boolean(draft && note !== draft.note);

  const navigationLocked=busy||dirty||sourceDirty||loading||loadFailed;
  const guideLocked=busy||dirty||sourceDirty;
  const navigationState=useRef({page,locked:navigationLocked,guideLocked,draft:Boolean(draft)});
  navigationState.current={page,locked:navigationLocked,guideLocked,draft:Boolean(draft)};
  function navigate(next:Page){
    if(next===page)return;
    if(next==='guide'?guideLocked:navigationLocked){setNavigationMessage('입력한 내용을 저장하거나 작성 취소한 뒤 메뉴를 이동해 주세요.');return}
    if(next!=='workspace'&&next!=='guide'&&!draft)return;
    window.history.pushState(null,'',`#${next}`);setPage(next);setNavigationMessage('');window.scrollTo(0,0);
  }
  useEffect(()=>{
    const back=()=>{const state=navigationState.current;const next=pageFromHash();
      if((next==='guide'?state.guideLocked:state.locked)||(next!=='workspace'&&next!=='guide'&&!state.draft)){
        window.history.replaceState(null,'',`#${state.page}`);
        setNavigationMessage('입력한 내용을 저장하거나 작성 취소한 뒤 메뉴를 이동해 주세요.');return;
      }
      setPage(next);setNavigationMessage('');window.scrollTo(0,0);
    };
    window.addEventListener('popstate',back);return()=>window.removeEventListener('popstate',back);
  },[]);
  useEffect(()=>{if(!navigationLocked)setNavigationMessage('')},[navigationLocked]);

  function adopt(d: Draft) {setDraft(d); setNote(d.note); setMonth(d.month); setError('')}
  function updateList(d: Draft) {setMonths(rows => [d, ...rows.filter(r => r.month !== d.month)].sort((a,b) => b.month.localeCompare(a.month)))}
  async function load() {
    setLoading(true); setLoadFailed(false); setError('');
    try {
      const s = await api<Session>('/session'); setToken(s.token); setSession(s);
      const list = await api<Draft[]>('/months'); setMonths(list);
      if (list.length) adopt([...list].sort((a,b) => b.updated_at.localeCompare(a.updated_at))[0]);
      else {setDraft(undefined);setNote('');setHistory([])}
    } catch (e) {setLoadFailed(true); setError((e as Error).message)} finally {setLoading(false)}
  }
  useEffect(() => {void load()}, []);
  useEffect(() => {
    if (!draft) return;
    let active = true;
    api<History[]>(`/months/${draft.month}/history`).then(rows => {if (active) setHistory(rows)}).catch(() => {if (active) setHistory([])});
    return () => {active = false};
  }, [draft?.month, draft?.revision]);
  useEffect(() => {
    const warn = (e: BeforeUnloadEvent) => {if (dirty || busy || sourceDirty) e.preventDefault()};
    window.addEventListener('beforeunload', warn);
    return () => window.removeEventListener('beforeunload', warn);
  }, [dirty, busy, sourceDirty]);

  async function save() {
    if (!draft || !dirty || lock.current) return;
    lock.current = true; setBusy(true); setError('');
    const submitted = note;
    try {
      const d = await api<Draft>(`/months/${draft.month}`, 'PATCH', {expected_revision: draft.revision, note: submitted});
      setDraft(d); updateList(d);
    } catch (e) {setError((e as Error).message)} finally {lock.current = false; setBusy(false)}
  }
  useEffect(() => {
    if (!dirty || busy || error || stopped) return;
    const timer = window.setTimeout(() => void save(), 900);
    return () => window.clearTimeout(timer);
  }, [note, draft, busy, error, stopped]);

  async function openMonth(target: string, create = false) {
    if (lock.current || loading || loadFailed) return;
    if (dirty || sourceDirty) {setError('저장하지 못한 메모가 있습니다. 먼저 저장하거나 최신 저장본을 불러와 주세요.'); return}
    lock.current = true; setBusy(true); setReading(true); setError('');
    try {
      const d = await api<Draft>(create ? '/months' : `/months/${target}`, create ? 'POST' : 'GET', create ? {month:target} : undefined);
      adopt(d); updateList(d);setListMessage('');
    } catch (e) {setError((e as Error).message)} finally {lock.current = false; setBusy(false); setReading(false)}
  }
  async function deleteMonth(row:Draft){
    if(navigationLocked||lock.current)return;
    if(!window.confirm(`${monthLabel(row.month)} 작업을 완전히 삭제할까요?\n\n메모·수정 이력·확정본과 이 월에서만 쓰는 보관 원본·출력 파일을 삭제합니다. 다른 월과 함께 쓰는 원본, 프로그램 기준은 유지됩니다. 프로그램 안에서 되돌릴 수 없습니다.`))return;
    lock.current=true;setBusy(true);setError('');
    try{
      const result=await api<{warning:string|null}>(`/months/${row.month}`,'DELETE',{expected_revision:row.revision},120000);
      setMonths(rows=>rows.filter(r=>r.month!==row.month));
      if(draft?.month===row.month){setDraft(undefined);setNote('');setHistory([]);setReviewProgress(undefined);setSourceProgress(undefined)}
      setListMessage(result.warning||`${monthLabel(row.month)} 작업을 완전히 삭제했습니다.`);
    }catch(e){setError((e as Error).message)}finally{lock.current=false;setBusy(false)}
  }
  async function reloadDraft() {
    if (!draft || lock.current || sourceDirty) return;
    if (dirty && !window.confirm('화면에 남은 메모 대신 최신 저장본을 불러옵니다. 필요한 내용은 먼저 복사해 주세요.')) return;
    lock.current = true; setBusy(true); setReading(true);
    try {const d = await api<Draft>(`/months/${draft.month}`); adopt(d); updateList(d)}
    catch (e) {setError((e as Error).message)} finally {lock.current = false; setBusy(false); setReading(false)}
  }
  async function shutdown() {
    if (dirty || busy || sourceDirty) {setError('메모 저장을 마친 뒤 종료해 주세요.'); return}
    try {await api('/shutdown', 'POST'); setStopped(true)} catch (e) {setError((e as Error).message)}
  }

  if (stopped) return <main className="stopped"><span className="brand-icon">C</span><h1>프로그램을 종료했습니다.</h1><p>저장한 월 작업은 다음 실행에서 이어갈 수 있습니다.</p><p>이 창을 닫으셔도 됩니다.</p></main>;
  return <>
    <header><div className="brand"><span className="brand-icon">C</span><div>촉매 월 마감<small>월별 자료와 마감 이력을 한곳에서</small></div></div><div className="header-right"><span className="local"><i/>내 PC에 저장</span><button onClick={() => void shutdown()} disabled={!session || busy}>프로그램 종료</button></div></header>
    <div className="navigation-shell">
      <nav aria-label="주요 메뉴">{mainMenu.map(([key,label])=><button key={key} className={pages[page].group===key?'active':''} aria-current={pages[page].group===key?'page':undefined} disabled={key==='guide'?guideLocked:navigationLocked||(key!=='workspace'&&!draft)} onClick={()=>navigate(key)}>{label}</button>)}</nav>
      {pages[page].group==='review'&&<nav className="subnav" aria-label="마감 검토 메뉴">{reviewMenu.map(([key,label])=><button key={key} className={page===key?'active':''} aria-current={page===key?'page':undefined} disabled={navigationLocked} onClick={()=>navigate(key)}>{label}</button>)}</nav>}
    </div>
    <main className={`workspace page-${page==='workspace'?'workspace':'detail'}`}>
      <section className="titlebar"><div><span className="eyebrow">{pages[page].label}</span><h1>{page==='guide'?'처음부터 따라 하는 마감 안내':draft ? monthLabel(draft.month) : '새로운 월 마감을 시작하세요'}</h1><p>{pages[page].hint}</p></div>{page==='workspace'?<form onSubmit={e => {e.preventDefault(); void openMonth(month, true)}}><label htmlFor="month">마감월</label><input id="month" type="month" min="2000-01" max="2099-12" required value={month} onChange={e => setMonth(e.target.value)}/><button className="primary" disabled={!session || navigationLocked}>월 작업 열기</button></form>:<button disabled={navigationLocked} onClick={()=>navigate('workspace')}>{page==='guide'?'월 작업으로 이동':'월 변경'}</button>}</section>
      {(sourceDirty||navigationMessage)&&<p className="navigation-notice" role="status">{navigationMessage||'입력 중입니다. 저장하거나 작성 취소하면 다른 메뉴로 이동할 수 있습니다.'}</p>}
      {!draft&&page!=='workspace'&&page!=='guide'&&!loading&&<div className="empty"><p>먼저 월 작업에서 마감월을 열어 주세요.</p><button onClick={()=>navigate('workspace')}>월 작업으로 이동</button></div>}
      {error && <div className="error" role="alert"><strong>확인이 필요합니다</strong><p>{error}</p>{loadFailed && <button disabled={loading} onClick={() => void load()}>다시 연결</button>}</div>}
      <div hidden={page!=='guide'}><Guide navigate={next=>navigate(!draft&&next!=='workspace'?'workspace':next)} disabled={navigationLocked} hasMonth={Boolean(draft)}/></div>
      <div hidden={page!=='workspace'}>{draft&&<Workflow draft={draft} review={reviewProgress} sources={sourceProgress} disabled={navigationLocked} navigate={navigate}/>}<div className="work-grid">
        <section className="paper month-list">
          <div className="section-head"><h2>월 작업 목록</h2><span>{months.length}개</span></div>
          {listMessage&&<p className="month-list-message" role="status">{listMessage}</p>}
          <div className="table-wrap"><table><thead><tr><th>마감월</th><th>상태</th><th>최근 저장</th><th>삭제</th></tr></thead><tbody>{months.map(row=><tr key={row.id} className={draft?.id===row.id?'selected':''}>
            <td><button onClick={()=>void openMonth(row.month)} disabled={navigationLocked} aria-current={draft?.id===row.id?'true':undefined}>{monthLabel(row.month)}</button></td>
            <td><span className={`status ${row.finalized?'complete':''}`}>{row.finalized?'확정 완료':'작업 중'}</span></td><td>{timeLabel(row.updated_at)}</td>
            <td><button className="month-list-action" disabled={navigationLocked} aria-label={`${monthLabel(row.month)} 작업 삭제`} onClick={()=>void deleteMonth(row)}>삭제</button></td>
          </tr>)}</tbody></table></div>
          {months.length===0&&<div className="empty"><span className="empty-icon">▤</span><h3>{loading?'저장한 작업을 확인하고 있습니다':loadFailed?'월 작업 목록을 읽지 못했습니다':'아직 월 작업이 없습니다'}</h3><p>오른쪽 위에서 마감월을 선택하고<br/>‘월 작업 열기’를 눌러 주세요.</p></div>}
          <div className="list-foot">삭제한 월은 복원할 수 없습니다. 같은 월을 다시 열면 새 작업을 시작합니다.</div>
        </section>
        <section className="paper editor" aria-label="선택한 월 작업"><div className="section-head"><h2>{draft ? `${monthLabel(draft.month)} 작업 메모` : '작업 상세'}</h2><span className="save-status" role="status">{busy ? '저장·처리 중…' : error && dirty ? '저장되지 않음' : dirty ? '저장 대기' : draft ? '저장 완료' : '작업 선택 전'}</span></div>{draft ? <><div className="editor-body"><div className="detail-summary"><div><span>진행 상태</span><strong>{draft.finalized?'확정 완료':'작업 중'}</strong></div><div><span>최근 저장</span><strong>{timeLabel(draft.updated_at)}</strong></div></div><label className="note-label" htmlFor="note">이번 달 준비사항</label><p className="hint">받아야 할 자료나 확인할 내용을 적어 두세요. 입력 후 자동 저장됩니다.</p><textarea id="note" disabled={reading || loading || sourceDirty || draft.finalized} value={note} maxLength={10000} onChange={e => setNote(e.target.value)} placeholder="예: 촉매사 적송재고 자료 확인 후 출하 실적과 대조"/><div className="note-bottom"><span>{note.length.toLocaleString()} / 10,000자</span><button className="primary" disabled={!dirty || busy} onClick={() => void save()}>지금 저장</button></div><button className="text-button" disabled={busy || sourceDirty} onClick={() => void reloadDraft()}>최신 저장본 불러오기</button></div><details className="history"><summary>저장 이력 <span>최근 {history.length}건</span></summary>{history.map(h => <div key={h.revision}><span>{({started:'월 작업 시작',note_saved:'작업 메모 저장',source_registered:'원본 자료 등록',source_selected:'채택 원본 변경',source_reviewed:'PDF 인식 정정·확인',hold_saved:'월별 미마감 수량 조정 저장',master_published:'기준 버전 저장',master_selected:'이번 달 기준 적용',month_reset:'이전 초안 보관 후 초기화'} as Record<string,string>)[h.kind] ?? h.kind}</span><time>{timeLabel(h.occurred_at)}</time></div>)}</details></> : <div className="empty"><h3>월 작업을 선택해 주세요</h3><p>선택한 월의 메모와 저장 이력이 표시됩니다.</p></div>}</section>
      </div></div><div hidden={page!=='review'&&page!=='review/hold'&&page!=='review/quantities'&&page!=='final'}>{draft&&<Closing key={`closing-${draft.id}`} draft={draft} visible={page==='review'||page==='review/hold'||page==='review/quantities'} onProgress={setReviewProgress} onNavigate={navigate} mode={page==='final'?'final':page==='review/hold'?'hold':page==='review/quantities'?'quantities':'overview'} onDirty={setClosingDirty} disabled={busy||dirty||sourceFormDirty||holdDirty||masterDirty||loading||loadFailed} begin={()=>{if(lock.current||dirty||sourceFormDirty||holdDirty||masterDirty||loading||loadFailed)return false;lock.current=true;setBusy(true);setReading(true);return true}} end={d=>{if(d){setDraft(d);updateList(d)}lock.current=false;setBusy(false);setReading(false)}}/>}</div><div hidden={page!=='sources'}>{draft && <Sources key={draft.id} onProgress={setSourceProgress} onNavigate={navigate} onDirty={setSourceDirty} draft={draft} disabled={busy || dirty || holdDirty || closingDirty || masterDirty || loading || loadFailed} begin={() => {if(lock.current || dirty || loading || loadFailed)return false;lock.current=true;setBusy(true);setReading(true);return true}} end={d => {if(d){setDraft(d);updateList(d)}lock.current=false;setBusy(false);setReading(false)}}/>}</div><div hidden={page!=='masters'}>{draft&&<Masters key={`masters-${draft.id}`} draft={draft} onDirty={setMasterDirty} disabled={busy||dirty||sourceFormDirty||holdDirty||closingDirty||loading||loadFailed} begin={()=>{if(lock.current||dirty||sourceFormDirty||holdDirty||closingDirty||loading||loadFailed)return false;lock.current=true;setBusy(true);return true}} end={d=>{if(d){setDraft(d);updateList(d)}lock.current=false;setBusy(false)}}/>}</div><div hidden={page!=='workspace'}><details className="workspace-reset"><summary>월 작업 초기화</summary>{draft&&<MonthReset key={`reset-${draft.id}`} draft={draft} disabled={busy||dirty||sourceDirty||loading||loadFailed} begin={()=>{if(lock.current||dirty||sourceDirty||loading||loadFailed)return false;lock.current=true;setBusy(true);return true}} end={d=>{if(d){adopt(d);updateList(d)}lock.current=false;setBusy(false)}}/>}</details></div><div hidden={page!=='review/evidence'}><label className="evidence-selector">확인할 자료<select aria-label="확인할 자료" value={evidencePage} disabled={navigationLocked} onChange={e=>setEvidencePage(e.target.value)}><option value="reconciliation">촉매사·ERP 수량 대조</option><option value="basis">제품 납품·BOM 연결</option><option value="pricing">단가·월계획</option><option value="holds">기존 미마감 입력·이력</option><option value="allocation">기존 배분 자료 검산</option></select></label><div hidden={evidencePage!=='basis'}>{draft&&<Basis key={`basis-${draft.id}`} draft={draft} disabled={busy||dirty||sourceDirty||loading||loadFailed}/>}</div><div hidden={evidencePage!=='pricing'}>{draft&&<Pricing key={`pricing-${draft.id}`} draft={draft} disabled={busy||dirty||sourceDirty||loading||loadFailed}/>}</div><div hidden={evidencePage!=='reconciliation'}>{draft&&<Reconciliation key={`reconciliation-${draft.id}`} draft={draft} disabled={busy||dirty||sourceDirty||loading||loadFailed}/>}</div><div hidden={evidencePage!=='holds'}>{draft&&<Holds key={`holds-${draft.id}`} draft={draft} onDirty={setHoldDirty} disabled={busy||dirty||sourceFormDirty||closingDirty||masterDirty||loading||loadFailed||Boolean(draft.finalized)} begin={()=>{if(lock.current||dirty||sourceFormDirty||masterDirty||loading||loadFailed)return false;lock.current=true;setBusy(true);setReading(true);return true}} end={d=>{if(d){setDraft(d);updateList(d)}lock.current=false;setBusy(false);setReading(false)}}/>}</div><div hidden={evidencePage!=='allocation'}>{draft&&<Allocation key={`allocation-${draft.id}`} draft={draft} disabled={busy||dirty||sourceDirty||loading||loadFailed}/>}</div></div><footer><span>자료 보관 폴더 <strong>{session?.data_dir ?? '연결 확인 중'}</strong></span><span>자동 저장은 마감 확정과 구분됩니다.</span></footer>
    </main>
  </>;
}

createRoot(document.getElementById('root')!).render(<App/>);
