import type {Draft} from './api';
import type {Page} from './navigation';

export type ReviewProgress={month:string;revision:number;loading:boolean;error:boolean;ready:boolean;finalized:boolean;review:number;items:number};
export type SourceProgress={month:string;revision:number;loading:boolean;error:boolean;selected:number;registered:number};

export function Workflow({draft,review,sources,disabled,navigate}:{draft:Draft;review?:ReviewProgress;sources?:SourceProgress;disabled:boolean;navigate:(page:Page)=>void}){
  const r=review?.month===draft.month&&review.revision===draft.revision&&!review.loading&&!review.error?review:undefined;
  const s=sources?.month===draft.month&&sources.revision===draft.revision&&!sources.loading&&!sources.error?sources:undefined;
  const failed=Boolean((review?.month===draft.month&&review.error)||(sources?.month===draft.month&&sources.error));
  const finalized=Boolean(draft.finalized);
  const next:Page=finalized?'final':s?.selected===0?'sources':r?.ready?'final':'review';
  const title=finalized?'확정한 보고서를 내려받으세요.':s?.selected===0?'이번 달 원본 자료를 등록해 주세요.':r?.ready?'검토를 마쳤습니다. 마감을 확정해 주세요.':r?(r.review?`확인이 필요한 ${r.review}개 품목부터 살펴보세요.`:'계산에 필요한 자료를 확인해 주세요.'):failed?'자료 상태를 불러오지 못했습니다. 검토 화면에서 다시 확인해 주세요.':'자료 상태와 계산 결과를 확인하고 있습니다.';
  return <section className="workflow-overview" aria-label="이번 달 작업 순서">
    <div className="workflow-next"><div><span className="eyebrow">지금 할 일</span><h2>{title}</h2><p>자료를 준비하고, 필요한 수량을 조정한 뒤 보고서를 저장합니다.</p></div><button className="primary" disabled={disabled||(!r&&!finalized&&!failed&&s?.selected!==0)} onClick={()=>navigate(next)}>{next==='sources'?'자료 등록 시작':next==='final'?(finalized?'확정본 출력하기':'확정·출력으로 이동'):'이어서 검토하기'} <span aria-hidden="true">→</span></button></div>
    <div className="workflow-steps">{([
      ['sources','자료 등록',s?`이번 달 사용 ${s.selected}종 · 등록 파일 ${s.registered}개`:'등록 상태 확인 중','촉매사 자료 · ERP · 제품 수불'],
      ['review','마감 검토',r?(r.review?`확인 필요 ${r.review}종`:`${r.items}종 계산 확인`):'계산 상태 확인 중','미마감 · 공장별 수량 조정'],
      ['final','확정·출력',finalized?'확정 완료':r?.ready?'확정 가능':'검토 후 확정','계산서 · 희성 자료 · 종합 보고서'],
    ] as const).map(([key,label,status,description],index)=><button key={key} disabled={disabled} className={`workflow-step ${next===key?'next':''}`} onClick={()=>navigate(key)}><span className="step-number">{index+1}</span><div><strong>{label}</strong><span>{description}</span><small>{status}</small></div><span aria-hidden="true">→</span></button>)}</div>
  </section>;
}
