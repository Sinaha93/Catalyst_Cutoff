import {Holds} from './Holds';
import {Reconciliation} from './Reconciliation';
import {Allocation} from './Allocation';
import {Pricing} from './Pricing';
import {Basis} from './Basis';
import {useEffect, useRef, useState} from 'react';
import {createRoot} from 'react-dom/client';
import {api, setToken, type Draft, type Session, type History} from './api';
import './style.css';
import {Sources} from './Sources';

function initialMonth() {const d = new Date(); d.setMonth(d.getMonth() - 1, 1); return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`}
const monthLabel = (m: string) => `${m.slice(0, 4)}년 ${Number(m.slice(5))}월`;
const timeLabel = (s: string) => new Date(s).toLocaleString('ko-KR', {month:'2-digit', day:'2-digit', hour:'2-digit', minute:'2-digit', second:'2-digit'});

function App() {
  const [session, setSession] = useState<Session>();
  const [months, setMonths] = useState<Draft[]>([]);
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
  const sourceDirty = sourceFormDirty || holdDirty;
  const [stopped, setStopped] = useState(false);
  const lock = useRef(false);
  const dirty = Boolean(draft && note !== draft.note);

  function adopt(d: Draft) {setDraft(d); setNote(d.note); setMonth(d.month); setError('')}
  function updateList(d: Draft) {setMonths(rows => [d, ...rows.filter(r => r.month !== d.month)].sort((a,b) => b.month.localeCompare(a.month)))}
  async function load() {
    setLoading(true); setLoadFailed(false); setError('');
    try {
      const s = await api<Session>('/session'); setToken(s.token); setSession(s);
      const list = await api<Draft[]>('/months'); setMonths(list);
      if (list.length) adopt([...list].sort((a,b) => b.updated_at.localeCompare(a.updated_at))[0]);
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
      adopt(d); updateList(d);
    } catch (e) {setError((e as Error).message)} finally {lock.current = false; setBusy(false); setReading(false)}
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
    <nav aria-label="주요 메뉴"><button className="active" aria-current="page">월 작업</button><button disabled={!draft} onClick={() => document.querySelector('.sources')?.scrollIntoView({behavior:'smooth'})}>자료 등록</button>{['마감 검토','확정·출력','기준 관리'].map(label => <button key={label} disabled title="다음 구현 단계에서 연결됩니다.">{label}<small>준비 중</small></button>)}</nav>
    <main className="workspace">
      <section className="titlebar"><div><span className="eyebrow">월별 작업 관리</span><h1>{draft ? monthLabel(draft.month) : '새로운 월 마감을 시작하세요'}</h1><p>저장한 작업을 이어서 열고, 해당 월의 준비사항을 기록합니다.</p></div><form onSubmit={e => {e.preventDefault(); void openMonth(month, true)}}><label htmlFor="month">마감월</label><input id="month" type="month" min="2000-01" max="2099-12" required value={month} onChange={e => setMonth(e.target.value)}/><button className="primary" disabled={!session || busy || dirty || sourceDirty || loading || loadFailed}>월 작업 열기</button></form></section>
      <div className="stage-notice"><span className="pill">1차 개발 · 원본 등록·검산</span><span>희성·유미코아 원본과 ERP 입고·수불, 글로비스 실제 입고를 보관하고 검산합니다. 원천 대조·보류 처리와 배분 검토를 지원합니다. 월 확정은 후속 단계입니다.</span></div>
      {error && <div className="error" role="alert"><strong>확인이 필요합니다</strong><p>{error}</p>{loadFailed && <button disabled={loading} onClick={() => void load()}>다시 연결</button>}</div>}
      <div className="work-grid">
        <section className="paper month-list"><div className="section-head"><h2>월 작업 목록</h2><span>{months.length}개</span></div><div className="table-wrap"><table><thead><tr><th>마감월</th><th>상태</th><th>최근 저장</th></tr></thead><tbody>{months.map(row => <tr key={row.id} className={draft?.id === row.id ? 'selected' : ''}><td><button onClick={() => void openMonth(row.month)} disabled={busy || dirty || sourceDirty || loading || loadFailed} aria-current={draft?.id === row.id ? 'true' : undefined}>{monthLabel(row.month)}</button></td><td><span className="status">작업 중</span></td><td>{timeLabel(row.updated_at)}</td></tr>)}</tbody></table></div>{months.length === 0 && <div className="empty"><span className="empty-icon">▤</span><h3>{loading ? '저장한 작업을 확인하고 있습니다' : loadFailed ? '월 작업 목록을 읽지 못했습니다' : '아직 월 작업이 없습니다'}</h3><p>오른쪽 위에서 마감월을 선택하고<br/>‘월 작업 열기’를 눌러 주세요.</p></div>}<div className="list-foot">같은 월을 다시 열면 기존 초안을 이어서 사용합니다.</div><div className="next-card"><span className="eyebrow">원본 자료</span><h3>원본 자료 등록</h3><p>아래에서 원본 자료를 등록합니다. BOM·경로 연결과 단가·계획 검토를 지원합니다. 원천 수량 대조·보류 처리·배분 검토를 지원하며 월 확정은 후속 단계입니다.</p><div className="source-tags"><span>출하 실적</span><span>적송재고 PDF</span><span>ERP 수불</span><span>BOM</span></div></div></section>
        <section className="paper editor" aria-label="선택한 월 작업"><div className="section-head"><h2>{draft ? `${monthLabel(draft.month)} 작업 메모` : '작업 상세'}</h2><span className="save-status" role="status">{busy ? '저장·처리 중…' : error && dirty ? '저장되지 않음' : dirty ? '저장 대기' : draft ? '저장 완료' : '작업 선택 전'}</span></div>{draft ? <><div className="editor-body"><div className="detail-summary"><div><span>진행 상태</span><strong>작업 중</strong></div><div><span>최근 저장</span><strong>{timeLabel(draft.updated_at)}</strong></div></div><label className="note-label" htmlFor="note">이번 달 준비사항</label><p className="hint">받아야 할 자료나 확인할 내용을 적어 두세요. 입력 후 자동 저장됩니다.</p><textarea id="note" disabled={reading || loading || sourceDirty} value={note} maxLength={10000} onChange={e => setNote(e.target.value)} placeholder="예: 촉매사 적송재고 자료 확인 후 출하 실적과 대조"/><div className="note-bottom"><span>{note.length.toLocaleString()} / 10,000자</span><button className="primary" disabled={!dirty || busy} onClick={() => void save()}>지금 저장</button></div><button className="text-button" disabled={busy || sourceDirty} onClick={() => void reloadDraft()}>최신 저장본 불러오기</button></div><details className="history"><summary>저장 이력 <span>최근 {history.length}건</span></summary>{history.map(h => <div key={h.revision}><span>{({started:'월 작업 시작',note_saved:'작업 메모 저장',source_registered:'원본 자료 등록',source_selected:'채택 원본 변경',source_reviewed:'PDF 인식 정정·확인',hold_saved:'월별 보류·해소 저장'} as Record<string,string>)[h.kind] ?? h.kind}</span><time>{timeLabel(h.occurred_at)}</time></div>)}</details></> : <div className="empty"><h3>월 작업을 선택해 주세요</h3><p>선택한 월의 메모와 저장 이력이 표시됩니다.</p></div>}</section>
      </div>{draft && <Sources key={draft.id} onDirty={setSourceDirty} draft={draft} disabled={busy || dirty || holdDirty || loading || loadFailed} begin={() => {if(lock.current || dirty || loading || loadFailed)return false;lock.current=true;setBusy(true);setReading(true);return true}} end={d => {if(d){setDraft(d);updateList(d)}lock.current=false;setBusy(false);setReading(false)}}/>}{draft&&<Basis key={`basis-${draft.id}`} draft={draft} disabled={busy||dirty||sourceDirty||loading||loadFailed}/>}{draft&&<Pricing key={`pricing-${draft.id}`} draft={draft} disabled={busy||dirty||sourceDirty||loading||loadFailed}/>}{draft&&<Reconciliation key={`reconciliation-${draft.id}`} draft={draft} disabled={busy||dirty||sourceDirty||loading||loadFailed}/>}{draft&&<Holds key={`holds-${draft.id}`} draft={draft} onDirty={setHoldDirty} disabled={busy||dirty||sourceFormDirty||loading||loadFailed} begin={()=>{if(lock.current||dirty||sourceFormDirty||loading||loadFailed)return false;lock.current=true;setBusy(true);setReading(true);return true}} end={d=>{if(d){setDraft(d);updateList(d)}lock.current=false;setBusy(false);setReading(false)}}/>}{draft&&<Allocation key={`allocation-${draft.id}`} draft={draft} disabled={busy||dirty||sourceDirty||loading||loadFailed}/>}<footer><span>자료 보관 폴더 <strong>{session?.data_dir ?? '연결 확인 중'}</strong></span><span>자동 저장은 마감 확정과 구분됩니다.</span></footer>
    </main>
  </>;
}

createRoot(document.getElementById('root')!).render(<App/>);
