import {useEffect, useRef, useState} from 'react';
import type {Page} from './navigation';
import './guide.css';

const steps=[
  {title:'마감월을 여세요',menu:'월 작업',page:'workspace',image:'month',focus:'마감월과 ‘월 작업 열기’',intro:'먼저 어느 달을 마감할지 정합니다. 같은 달을 다시 열면 하던 작업을 이어갑니다.',actions:['상단 ‘월 작업’을 누릅니다.','오른쪽 위 마감월에서 작업할 달을 고릅니다.','‘월 작업 열기’를 누릅니다.'],done:'화면 제목에 원하는 마감월이 나오면 준비됐습니다.',note:'작업 메모는 자동 저장됩니다. 메모가 저장됐다고 마감이 확정된 것은 아닙니다.'},
  {title:'이번 달 자료를 넣으세요',menu:'자료 등록',page:'sources',image:'sources',focus:'자료 종류 → 파일 선택 → 사용 선택',intro:'파일을 보관한 다음, 내용을 확인하고 계산에 사용할 파일을 선택합니다.',actions:['‘이번 달 원본’에서 희성 출하·ERP 입고 등 넣을 자료 종류를 고릅니다.','파일을 선택하고, 기간 확인란이 나오면 자료의 조회 기간을 확인한 뒤 체크합니다.','‘원본 보관·읽기’를 누르고 품번·수량·기준월을 확인합니다.','‘이번 달 원본으로 사용’을 누릅니다. 필요한 자료마다 반복합니다.'],done:'자료 카드에 ‘이번 달 사용’이 표시돼야 계산에 들어갑니다.',note:'적송재고 PDF는 전월 말 자료입니다. 예를 들어 10월 마감에는 9월 말 PDF를 넣습니다. PDF는 화면에서 인식된 품번과 수량도 확인합니다.'},
  {title:'확인할 품목부터 보세요',menu:'마감 검토 → 전체 검토',page:'review',image:'review',focus:'왼쪽 품목 선택 / 오른쪽 계산 결과',intro:'프로그램이 계산한 수량과 공장 배분을 확인하는 화면입니다.',actions:['상단 ‘마감 검토’를 누릅니다.','‘확인할 품목만’을 체크해 먼저 확인이 필요한 품목을 봅니다.','왼쪽에서 품번을 누르고 오른쪽에 나온 확인 내용과 수량을 읽습니다.','차이가 있으면 ‘원천 구성·근거 보기’ 또는 ‘계산 근거’에서 원본을 확인합니다.'],done:'품목에 남은 확인 문제를 해결하면 ‘검토 완료’로 표시됩니다.',note:'‘조건에 맞는 품목이 없습니다’는 현재 검색·체크 조건에 해당하는 품목이 없다는 뜻입니다. 전체를 보려면 검색을 지우고 체크를 해제하세요.'},
  {title:'이번 달에 남길 수량을 입력하세요',menu:'마감 검토 → 미마감 조정',page:'review/hold',image:'hold',focus:'두 수량 입력칸과 ‘검토 내용 저장’',intro:'이번 달에 마감하지 않을 수량이나, 지난달에 남겼다가 이번 달에 마감할 수량이 있을 때 사용합니다.',actions:['‘미마감 조정’을 누르고 왼쪽에서 품번을 고릅니다.','‘이번 달 추가 미마감’에는 이번 달 물량 중 다음 달로 넘길 수량을 적습니다.','‘전월 미마감 중 이번 달 마감’에는 지난달에 남긴 물량 중 이번 달에 마감할 수량을 적습니다.','변경 사유와 근거를 적고 ‘검토 내용 저장’을 누릅니다.'],done:'저장 안내가 나오고 위쪽 마감 수량·미마감 수량이 바뀌었는지 확인합니다.',note:'미마감 입력칸의 빈칸은 저장할 때 0으로 처리합니다. 전월 미마감을 모두 이번 달에 마감하는 것은 아닙니다. 실제 마감할 수량만 적으세요.'},
  {title:'공장별 수량을 확인하세요',menu:'마감 검토 → 공장별 수량 조정',page:'review/quantities',image:'quantities',focus:'자동 계산과 적용 수량 비교',intro:'자동 배분을 기본으로 사용합니다. 이번 달 실제 마감이 다를 때만 공장별 수량을 조정합니다.',actions:['‘공장별 수량 조정’을 누르고 품번을 고릅니다.','‘자동 계산’과 ‘적용 수량’을 비교합니다.','다르게 마감할 공장이 있으면 해당 수량을 고칩니다. 여러 공장을 바꿔야 하면 함께 입력합니다.','사유와 근거를 적고 ‘검토 내용 저장’을 누릅니다. 총합과 검산 차이를 확인합니다.'],done:'전체 마감 수량과 공장별 합계가 맞고 검산 차이가 0이어야 합니다.',note:'공장 수량의 빈칸은 자동 계산을 사용한다는 뜻이고, 0은 그 공장을 0개로 마감한다는 뜻입니다. 글로비스는 실제 제품 입고 × BOM 기준으로 고정되어 일반 배분처럼 수정하지 않습니다.'},
  {title:'확정하고 엑셀을 받으세요',menu:'확정·출력',page:'final',image:'final',focus:'① 이번 달 마감 확정 ② 엑셀 생성·다운로드',intro:'검토 결과를 확정본으로 보관하고, 그 확정본으로 보고서를 만듭니다.',actions:['‘확정·출력’을 누릅니다.','마감 수량·금액과 확인할 항목을 봅니다. ‘확정 가능’ 상태인지 확인합니다.','‘이번 달 마감 확정’을 누릅니다.','출력할 확정 버전을 확인한 뒤 ‘엑셀 생성·다운로드’를 누릅니다.'],done:'다운로드한 파일의 종합·거래처별 계산서·희성 마감자료·미마감 내역을 확인합니다.',note:'확정 후 수정하려면 아래 ‘백업·재작업·전월 이월 연결’을 펼치고 사유를 입력해 ‘새 확정 버전 작업 시작’을 누릅니다. 다시 확정·출력해야 수정한 결과가 새 엑셀에 반영됩니다.'},
] as const;
type Topic='steps'|'files'|'adjust'|'masters'|'terms'|'help';
const topics:readonly [Topic,string][]=[['steps','마감 따라하기'],['files','무슨 파일을 넣나요?'],['adjust','수량 수정 이해하기'],['masters','저장된 기준 관리'],['terms','용어 쉽게 보기'],['help','막혔을 때']];
const monthlyFiles=[
 ['희성 출하 원본','희성이 보내준 출하 첫 시트','이번 달','공장 배분·이월을 직접 가공한 두 번째 시트는 프로그램이 결과로 만듭니다.'],
 ['유미코아 납품 Summary','유미코아가 보내준 마감 엑셀','이번 달','1차·2차 마감 표기는 그대로 읽고, 최종 결과와 대조합니다.'],
 ['ERP 촉매 입고','기간별구매거래처입고현황','이번 달','촉매가 ERP에서 어느 거래처로 입고됐는지 읽습니다.'],
 ['제품 창고 수불','제품 창고별 수불집계조회','이번 달','제품 납품 흐름과 공장 배분 비율의 근거입니다.'],
 ['반제품 창고 수불','반제품 창고별 수불집계조회','이번 달','H 품번 등 반제품 경로의 근거입니다.'],
 ['글로비스 실제 입고','글로비스 제품 입고 원장','이번 달','촉매 입고가 아니라 제품의 실제 입고 자료입니다.'],
 ['희성·유미코아 전월 적송재고 PDF','각 촉매사의 기말적송재고 PDF','전월 말','10월 마감이라면 9월 말 재고를 넣습니다.'],
 ['ERP 단가·월계획','그 달에 적용할 단가·계획 엑셀','이번 달','자료 등록의 ‘기준·계획 자료’에서 넣습니다.'],
];
const questions=[
 ['파일을 넣었는데 계산에 안 들어가요.','‘원본 보관·읽기’는 파일을 보관하고 읽는 단계입니다. 읽기 결과를 확인한 다음 ‘이번 달 원본으로 사용’까지 눌러야 합니다. ‘확인 필요’로 나오면 표시된 원본 행이나 PDF 인식값을 먼저 확인하세요.'],
 ['메뉴가 회색이라 못 눌러요.','입력 중인 수정 내용을 저장하거나 ‘작성 취소’를 누르세요. 처리 중이면 완료될 때까지 기다리세요. 화면 이동 때문에 작성 중인 값이 사라지지 않도록 막는 것입니다.'],
 ['확인할 품목이 없다고 나와요.','현재 검색·체크 조건에 해당하는 품목이 없다는 뜻입니다. 전체 목록을 보려면 검색어를 지우고 ‘확인할 품목만’ 체크를 해제하세요.'],
 ['저장했는데 엑셀 수량이 예전 값이에요.','엑셀은 확정본으로 만듭니다. 수정 내용을 저장한 뒤 새 버전으로 마감을 확정하고, 출력할 확정 버전에서 새 버전을 골라 다시 다운로드하세요.'],
 ['마감 확정 버튼을 못 눌러요.','확인할 항목이 남아 있는지 보세요. ‘확인할 품목 검토하기’로 돌아가 원본 차이, 미마감, 공장 배분, 단가 등 표시된 문제를 해결해야 합니다.'],
 ['숫자를 적었는데 위쪽 결과가 그대로예요.','‘검토 내용 저장’을 눌렀는지 확인하세요. 아래에 ‘입력 중 · 아직 저장하지 않음’이 보이면 적용 전입니다. 저장 오류가 나오면 그 안내부터 확인하세요.'],
 ['기존 파일을 잘못 골랐어요.','자료 등록에서 올바른 수정본을 보관·읽고, 이번 달 원본으로 선택해 교체하세요. 원본 교체로 영향을 받는 조정은 다시 확인해야 합니다. 예전 원본과 이력은 보존됩니다.'],
 ['다른 컴퓨터로 옮기려면요?','‘확정·출력’ 아래 ‘백업·재작업·전월 이월 연결’에서 ‘자료 전체 백업’을 만드세요. 새 컴퓨터의 빈 자료 폴더에 백업을 풀고 그 폴더를 선택합니다. GitHub 프로그램 코드만 가져오면 원본·기준·마감 이력은 따라오지 않습니다.'],
 ['지난달 미마감을 이번 달에 가져오려면요?','‘확정·출력’ 아래 ‘전월 이월 연결’에서 사용할 전월 확정본을 골라 연결합니다. 촉매사 PDF 이월과 다르면 근거를 보고 구성부터 확인합니다. 전월의 새 확정본이 생겨도 연결을 자동으로 바꾸지 않습니다.'],
 ['월 작업 초기화는 전부 지우는 건가요?','아닙니다. 이번 달 조정 입력을 다시 시작하는 기능입니다. 이전 초안, 원본, 저장된 기준, 전월 이월 연결과 확정 이력은 보존됩니다. 단순히 수량 하나를 되돌리려면 초기화 대신 ‘저장된 수정값 해제’를 사용하세요.'],
 ['과거 월 작업을 삭제하려면요?','‘월 작업’ 목록에서 해당 월의 ‘삭제’를 누르고 확인창의 마감월을 확인하세요. 메모·수정 이력·확정본과 그 월에서만 쓰는 보관 원본·출력 파일을 삭제합니다. 다른 월과 공유하는 원본과 프로그램 기준은 유지됩니다. 삭제한 월은 프로그램에서 복원할 수 없으며, 같은 월을 다시 열면 새 작업입니다. 다른 월이 전월 이월로 사용 중이면 연결된 월을 먼저 정리해야 합니다.'],
 ['촉매사 자료와 ERP 입고 수량이 달라요.','먼저 ‘전체 검토’의 ‘원천 구성·근거 보기’나 ‘계산 근거’에서 두 자료의 기간·이월·입고를 대조하세요. 월말 미입고 등 차이의 이유를 확인한 뒤 ‘추가 조정 열기’ → ‘계산 기준 확인’에서 사용할 구성을 정하고 사유·근거를 저장합니다. 서로 다른 자료의 이월·입고를 임의로 합쳐 맞추지 않습니다.'],
 ['글로비스 수량은 왜 직접 못 고쳐요?','글로비스는 실제 제품 입고 수량에 BOM 소요량을 적용해 촉매를 마감합니다. 다른 공장처럼 비율이나 임의 수량으로 바꾸지 않습니다. 수량이 다르면 글로비스 입고 원본, BOM과 촉매 직사급 예외를 먼저 확인하세요.'],
];

export function Guide({navigate,disabled,hasMonth}:{navigate:(page:Page)=>void;disabled:boolean;hasMonth:boolean}){
 const [topic,setTopic]=useState<Topic>('steps'),[step,setStep]=useState(0),[query,setQuery]=useState('');
 const [zoom,setZoom]=useState<{src:string;alt:string}|null>(null);const dialog=useRef<HTMLDialogElement>(null);
 useEffect(()=>{if(zoom&&!dialog.current?.open)dialog.current?.showModal();else if(!zoom&&dialog.current?.open)dialog.current.close()},[zoom]);
 const current=steps[step];
 const openWork=(page:Page)=>navigate(hasMonth?page:'workspace');
 function picture(image:string,alt:string){return <figure className="guide-picture"><button onClick={()=>setZoom({src:`/guide/${image}.png`,alt})} aria-label={`${alt} 크게 보기`}><img src={`/guide/${image}.png`} alt={alt} loading="lazy" width="1920" height="1000"/><span>화면 크게 보기</span></button><figcaption>실제 프로그램을 가상 자료로 촬영한 예시입니다. 품번·수량은 실제 마감 실적이 아닙니다.</figcaption></figure>}
 return <section className="guide" aria-label="사용 가이드">
  <div className="guide-intro"><p><strong>매월 하는 일은 세 가지입니다.</strong> 자료를 넣고 → 계산 결과를 검토하고 → 확정한 엑셀을 받습니다.</p><span>BOM·경로를 매월 다시 만드는 작업은 아닙니다.</span>{!hasMonth&&<p className="guide-start-hint">아직 월을 열지 않으셨다면 1단계부터 시작하세요. 작업 화면으로 이동할 때 먼저 마감월을 열게 됩니다.</p>}</div>
  <nav className="guide-topics" aria-label="가이드 주제">{topics.map(([id,label])=><button key={id} aria-pressed={topic===id} className={topic===id?'selected':''} onClick={()=>setTopic(id)}>{label}</button>)}</nav>
  {topic==='steps'&&<>
   <div className="guide-step-menu" aria-label="마감 순서">{steps.map((s,i)=><button key={s.page} aria-pressed={step===i} className={step===i?'selected':''} onClick={()=>setStep(i)}><span>{i+1}</span>{s.menu.split(' → ').at(-1)}</button>)}</div>
   <article className="guide-article">
    <div className="guide-heading"><div><span className="eyebrow">{step+1} / {steps.length} 단계 · {current.menu}</span><h2>{current.title}</h2><p>{current.intro}</p></div><button disabled={disabled} onClick={()=>openWork(current.page)}>{!hasMonth&&current.page!=='workspace'?'먼저 월 작업 열기':'이 작업 화면으로 이동 →'}</button></div>
    <div className="guide-instructions"><ol>{current.actions.map(x=><li key={x}>{x}</li>)}</ol><div className="guide-check"><strong>여기까지 됐으면 다음으로</strong><p>{current.done}</p><span>{current.note}</span></div></div>
    {step===3&&<p className="guide-note">남길 수량도, 전월 물량 중 마감할 수량도 없으면 두 칸은 0으로 저장합니다. 전체 검토에 ‘미마감 없음 일괄 확인’이 나타나면 표시된 대상 품목을 확인한 뒤 한 번에 처리할 수 있습니다.</p>}
    <div className="guide-step-footer"><button disabled={step===0} onClick={()=>setStep(step-1)}>← 이전 단계</button><span>{step+1} / {steps.length}</span>{step<steps.length-1?<button className="primary" onClick={()=>setStep(step+1)}>다음 단계 →</button>:<button onClick={()=>setTopic('help')}>막혔을 때 보기</button>}</div>
    <div className="guide-image-label">화면에서 볼 곳: <strong>{current.focus}</strong></div>{picture(current.image,current.menu+' 예시 화면')}
   </article>
  </>}
  {topic==='files'&&<article className="guide-article"><h2>이번 달 실적은 파일로, 계속 쓰는 기준은 프로그램에</h2><p>‘이번 달 원본’과 ‘기준·계획 자료’에서 아래 자료를 등록합니다. 받은 원본 파일은 그대로 넣으세요.</p><div className="table-wrap"><table><thead><tr><th>프로그램에서 고를 종류</th><th>넣을 파일</th><th>기간</th><th>알아둘 점</th></tr></thead><tbody>{monthlyFiles.map(r=><tr key={r[0]}>{r.map((v,i)=><td key={i}>{v}</td>)}</tr>)}</tbody></table></div><h3>매월 다시 넣지 않아도 되는 것</h3><div className="guide-cards"><div><h4>BOM</h4><p>제품에 어떤 촉매가 몇 개 들어가는지입니다. 처음 등록하고, 구성이 바뀔 때만 BOM 엑셀을 수정해 새 기준으로 반영합니다.</p></div><div><h4>경로·공장·ERP 마감처</h4><p>세종→울산3 같은 연결입니다. 처음 등록한 뒤 ‘기준 관리’에서 고칩니다. 이번 달에 적용된 버전은 확인합니다.</p></div><div><h4>단가 예외</h4><p>가단가·정단가 예외는 적용 기간과 근거를 저장합니다. 이번 달에만 다른 단가를 쓴다면 월 검토에서 조정합니다.</p></div></div><div className="guide-note"><strong>결과는 제가 가공해서 넣어야 하나요?</strong><p>희성 공장 배분·이월 가공 시트, 거래처별 계산서, 종합표·그래프, 미마감 내역은 검토·확정 후 프로그램이 엑셀로 만듭니다.</p></div><p>구매납품품목조회 같은 입고 상세는 대조 근거로 쓸 수 있지만 ‘ERP 촉매 입고’에는 기간별구매거래처입고현황 집계 양식을 넣습니다.</p><button disabled={disabled} onClick={()=>navigate('sources')}>자료 등록으로 이동 →</button></article>}
  {topic==='adjust'&&<article className="guide-article"><h2>미마감 두 칸은 각각 무엇인가요?</h2><p>미마감은 <strong>이번 달에 마감하지 않고 다음 달로 남기는 수량</strong>입니다.</p><div className="guide-cards two"><div><h3>이번 달 추가 미마감</h3><p>이번 달 들어온 물량 중 이번 달에 마감하지 않을 수량입니다.</p><div className="guide-example">예: 이번 달 입고 100개 중 10개를 남기려면 <strong>10</strong>을 적습니다.</div></div><div><h3>전월 미마감 중 이번 달 마감</h3><p>지난달에 남겨 둔 물량 중 이번 달에 마감할 수량입니다.</p><div className="guide-example">예: 전월 미마감 20개 중 5개를 마감하려면 <strong>5</strong>를 적습니다. 나머지 15개는 계속 남습니다.</div></div></div><div className="guide-equation"><strong>위 예시를 합치면</strong><p>이번 달 마감은 <b>100 − 10 + 5 = 95개</b><br/>다음 달로 남길 수량은 <b>20 − 5 + 10 = 25개</b></p><small>다른 조정이 없고, 전월 미마감 20개가 연결된 경우의 설명용 예시입니다.</small></div><h3>빈칸과 0은 같나요?</h3><table><thead><tr><th>입력하는 곳</th><th>빈칸</th><th>0 입력</th></tr></thead><tbody><tr><td>미마감 수량</td><td>저장할 때 0으로 처리</td><td>해당 조정 수량 없음</td></tr><tr><td>공장별 수량</td><td>자동 계산값 사용</td><td>해당 공장을 0개로 마감</td></tr></tbody></table><h3>버튼 세 개의 차이</h3><div className="guide-cards"><div><h4>검토 내용 저장</h4><p>입력한 값을 적용하고 다시 계산합니다. 사유·근거와 수정 이력이 남습니다.</p></div><div><h4>작성 취소</h4><p>지금 입력 중인 값을 버립니다. 이미 저장한 수정은 그대로 둡니다.</p></div><div><h4>저장된 수정값 해제</h4><p>이전에 저장한 해당 수정값을 해제합니다. 원래 계산 기준으로 돌아가며 해제 이력도 남습니다.</p></div></div><div className="guide-note"><strong>공장이 여러 곳이면요?</strong><p>같은 품목이라도 울산1·울산3·광주처럼 공장별로 각각 표시됩니다. 기본은 경로별 제품 수불 비율로 촉매를 배분합니다. 중간 납품처와 뒤쪽 현대·기아 창고 물량을 중복 합산하지 않습니다. 상세 공장 결과는 ERP용 지역 마감처로 합쳐 출력합니다.</p><p>같은 원본 제품 수량이 여러 상세 공장으로 나뉘어야 하면, ‘제품 수량 구분’에서 이번 달 제품 수량을 구분합니다. 촉매 마감 수량을 직접 고치는 것과 다릅니다.</p></div>{picture('hold','미마감 수량 입력 예시')}<button disabled={disabled} onClick={()=>navigate('review/hold')}>미마감 조정으로 이동 →</button></article>}
  {topic==='masters'&&<article className="guide-article"><h2>기준은 한 번 등록하고, 바뀔 때 관리합니다</h2><p>이곳은 매월 실적을 넣는 화면이 아니라 앞으로 계산할 때 쓸 연결 기준을 관리하는 화면입니다.</p><ol><li>상단 ‘기준 관리’에서 BOM·경로·단가 예외 중 바꿀 종류를 고릅니다.</li><li>BOM은 수정한 엑셀을 후보로 등록합니다. 경로·단가 예외는 기존 버전을 불러와 화면에서 수정할 수 있습니다.</li><li>언제부터 적용할지와 변경 사유를 적고 ‘기준 변경 내용 비교’로 변경점을 봅니다.</li><li>‘새 기준 버전 저장’ 후 ‘이번 달 적용 전 차이 보기’로 확인하고 이번 달에 적용합니다.</li></ol><div className="guide-note"><strong>적용 시작월·종료월은 왜 있나요?</strong><p>예전 마감은 예전 기준으로 남기고, 변경 기준을 어느 달부터 쓸지 정하기 위해서입니다. 종료월은 필요한 경우만 입력합니다. 예를 들어 10월부터 경로가 바뀌면 시작월을 10월로 저장합니다.</p><p>새 월을 처음 열면 그 달에 유효한 기준이 연결됩니다. 이미 열어 둔 월은 기준을 새로 저장해도 자동 교체되지 않으므로 적용까지 확인하세요.</p></div>{picture('masters','프로그램 기준 관리 예시')}<button disabled={disabled} onClick={()=>navigate('masters')}>기준 관리로 이동 →</button></article>}
  {topic==='terms'&&<article className="guide-article"><h2>화면의 말, 이렇게 읽으시면 됩니다</h2><dl className="guide-terms">{[
   ['적송재고 / 이월','촉매사 자료에서 전월 말에 남아 있다고 표시한 수량입니다. 당월 재고와 혼동하지 않습니다.'],
   ['미마감','이번 달 마감에서 남겨 다음 달로 넘기는 수량입니다. ERP 창고 재고와 항상 같은 숫자는 아닙니다.'],
   ['상세 마감 공장','현대기아 입력에 쓸 울산1·울산3·화성2 같은 세부 구분입니다.'],
   ['ERP 마감처','우리 ERP에 입력할 울산·화성·글로비스 같은 거래처 구분입니다. 울산1·울산3은 ERP용 울산으로 합칩니다.'],
   ['자동 계산 / 적용 수량','자동 계산은 원본·기준으로 계산한 수량이고, 적용 수량은 월별 수정을 반영해 실제 마감에 사용할 수량입니다.'],
   ['검산 차이','사용할 전체 수량, 공장 마감 합계와 미마감이 맞는지 확인한 차이입니다. 0이 아니면 구성부터 확인합니다.'],
   ['원천 선택','촉매사 자료와 ERP·이월 자료가 다를 때 어느 구성을 계산에 사용할지 근거를 정하는 조정입니다. 평소 매번 바꿀 필요는 없습니다.'],
   ['확정본 / 버전','그때의 원본·기준·수정·결과를 함께 보관한 기록입니다. 다시 확정하면 새 버전이 생기고 예전 버전도 남습니다.'],
  ].map(([term,meaning])=><div key={term}><dt>{term}</dt><dd>{meaning}</dd></div>)}</dl></article>}
  {topic==='help'&&<article className="guide-article"><h2>지금 막힌 부분을 찾아보세요</h2><label className="guide-search">궁금한 내용 검색<input type="search" value={query} onChange={e=>setQuery(e.target.value)} placeholder="예: 저장, 파일, 확정, 다른 컴퓨터"/></label><div className="guide-faq">{questions.filter(q=>q.join(' ').includes(query.trim())).map(([q,a])=><details key={q}><summary>{q}</summary><p>{a}</p></details>)}{!questions.some(q=>q.join(' ').includes(query.trim()))&&<p>해당 설명이 없습니다. 검색어를 짧게 바꾸거나 지워 주세요.</p>}</div></article>}
  <dialog ref={dialog} className="guide-zoom" aria-label="가이드 화면 확대" onClose={()=>setZoom(null)} onClick={e=>{if(e.target===e.currentTarget)dialog.current?.close()}}><div className="guide-zoom-header"><strong>{zoom?.alt}</strong><button autoFocus onClick={()=>dialog.current?.close()}>닫기</button></div>{zoom&&<img src={zoom.src} alt={zoom.alt}/>}</dialog>
 </section>;
}
