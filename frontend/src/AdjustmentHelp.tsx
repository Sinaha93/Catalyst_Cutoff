import {useRef, useId} from 'react';
import {createPortal} from 'react-dom';
import './adjustmentHelp.css';

export const adjustmentTopics = {
  source: {title:'계산 기준 확인', meaning:'이월과 입고 수량을 어느 자료에서 가져올지 정합니다.',
    when:'촉매사 자료와 ERP, 또는 연결한 전월 확정본에 실제 수량 차이가 있을 때 사용합니다. 평소에는 기본값인 PDF 이월 + 촉매사 입고를 사용하시면 됩니다.',
    example:'PDF 이월 10개 + 촉매사 입고 90개라면 계산할 전체 수량은 100개입니다. 일반 품목에 별도 미마감이 없으면 100개를 마감합니다.',
    result:'선택한 자료의 이월·입고로 마감 수량을 다시 계산합니다. 원본 파일의 숫자는 고치지 않습니다.',
    steps:['‘원천 구성·근거 보기’에서 자료별 이월·입고를 비교합니다.','아래 네 가지 중 근거가 맞는 구성을 선택합니다.','변경 사유와 파일·행 등의 근거를 적고 저장합니다.'],
    note:'ERP 입고 자료의 거래처를 선택하는 메뉴가 아닙니다. 마감처별 배분은 제품 납품·BOM·경로 기준으로 계산합니다.'},
  carry: {title:'이월 수정', meaning:'촉매사 PDF에서 가져온 전월 이월 수량을 이번 달 계산에서만 정정합니다.',
    when:'PDF에는 10개로 적혀 있지만 촉매사 확인 결과 실제 이월이 8개인 경우처럼, 이월 자체가 잘못됐을 때 사용합니다.',
    example:'PDF 원값 10개 → 적용할 이월 8개로 입력. 당월 입고 90개라면 전체 수량이 100개에서 98개로 바뀝니다.',
    result:'‘PDF 이월 원값’은 10개로 남고 ‘적용 이월’에 8개를 사용합니다. 비교 자료와 차이가 남으면 계산 기준도 확인합니다.',
    steps:['원본 PDF와 촉매사가 확인해 준 정정 수량을 확인합니다.','‘적용할 이월 수량’에 맞는 숫자를 적습니다.','사유·근거를 입력하고 저장한 뒤 적용 이월을 확인합니다.'],
    note:'10개 중 일부를 이번 달에 마감하지 않으려는 경우는 ‘미마감 조정’을 사용합니다. ERP·장부나 전월 확정본을 계산 기준으로 선택했다면 그 기준의 이월을 사용하므로 현재 적용 구성을 먼저 확인하세요.'},
  prices: {title:'단가', meaning:'선택한 촉매의 이번 달 마감처별 적용 단가를 바꿉니다.',
    when:'기본 단가와 다르게 정산하기로 했거나, 정단가가 나오지 않아 가단가를 적용할 때 사용합니다.',
    example:'울산 마감 100개 × 기본 단가 1,000원 = 100,000원. 이번 달 단가를 1,100원으로 바꾸면 110,000원이 됩니다.',
    result:'해당 월·촉매·마감처의 금액을 다시 계산합니다. 기준 관리에 저장한 기본 단가를 바꾸지는 않습니다.',
    steps:['변경할 마감처의 적용 단가를 적습니다.','‘정단가’ 또는 ‘가단가’를 선택합니다.','가격 확인 자료를 사유·근거로 적고 저장합니다.'],
    note:'앞으로 계속 사용할 기본 단가를 바꾸려면 ‘기준 관리 → 촉매 단가’에서 변경합니다.'},
  mapping: {title:'마감처 연결', meaning:'자동 계산으로 정하지 못한 촉매의 마감처와 배분 근거를 이번 달에 지정합니다.',
    when:'BOM 밖의 촉매나 직사급 품목 등에서 자동 연결을 완성하지 못했고, 별도로 확인한 납품 근거가 있을 때 사용합니다.',
    example:'마감할 촉매 100개를 울산·화성에 나눠야 하고 납품 근거가 각각 60·40이면, 두 행의 배분 근거 수량에 60·40을 적습니다. 자동 배분은 60개·40개가 됩니다.',
    result:'입력한 마감처·상세 공장·근거 수량으로 이번 달 배분을 계산합니다. 배분 근거 수량은 마감할 총량을 새로 만드는 값이 아닙니다.',
    steps:['ERP 마감처와 상세 공장을 확인합니다.','필요한 행을 추가하고 각 행에 배분 근거 수량을 입력합니다.','납품 자료 등 근거를 남기고 저장한 뒤 공장별 합계를 확인합니다.'],
    note:'계속 사용할 연결은 ‘기준 관리 → 경로·공장’에서 관리합니다. ERP 입고 때 임의로 넣은 거래처만 보고 정하지 않습니다. 글로비스는 이 메뉴로 임의 배분할 수 없습니다.'},
  splits: {title:'제품 수량 구분', meaning:'한데 묶인 제품 납품 수량을 실제로 납품된 상세 공장별로 나눠 적습니다.',
    when:'같은 제품이 여러 공장으로 가는데 수불 자료 한 행만으로 각 공장 수량을 알 수 없어 구분이 필요한 경우에 사용합니다.',
    example:'제품 이동 1,000개 중 울산1에 600개, 울산3에 400개를 납품했다면 해당 경로에 600·400을 적습니다. BOM을 적용한 뒤 촉매 배분 비율을 구합니다.',
    result:'제품 납품 근거와 촉매 배분 비율이 다시 계산됩니다. 여기에 적는 것은 제품 수량이며 촉매의 최종 마감 수량이 아닙니다.',
    steps:['표시된 제품·공장을 납품 기록과 맞춰 봅니다.','공장별 제품 수량을 입력하고 원본 합계와 맞는지 확인합니다.','사유·근거와 함께 저장하고 배분 결과를 확인합니다.'],
    note:'현재 구분이 필요한 경로만 표시됩니다. ‘공장별 수량 조정’은 계산된 촉매 마감 수량을 직접 바꾸는 별도 메뉴입니다.'},
  statement: {title:'촉매사 마감 차이 확인', meaning:'유미코아 원문에 적힌 마감 수량과 프로그램의 마감 수량이 다른 이유를 기록합니다.',
    when:'유미코아 원문과 실제 정산 조건이 달라 수량 차이가 생겼고, 그 차이가 맞다고 확인한 경우에 사용합니다.',
    example:'유미코아 원문 마감 100개 중 10개가 실제 미마감이라면, 먼저 미마감 조정으로 프로그램 마감을 90개로 만듭니다. 그다음 원문과 10개 차이 나는 이유를 기록합니다.',
    result:'수량을 바꾸지 않고 차이를 검토했다는 기록만 남깁니다.',
    steps:['원문 마감과 프로그램 마감 수량을 비교합니다.','수량이 잘못됐다면 먼저 이월·입고·미마감 등 원인을 수정합니다.','차이가 맞는 경우 그 이유와 근거를 적고 저장합니다.'],
    note:'희성에는 사용하지 않습니다. 차이를 확인하는 버튼만 눌러서는 잘못된 수량이 고쳐지지 않습니다.'},
} as const;
export type AdjustmentTopic = keyof typeof adjustmentTopics;

const choices = [
  ['PDF 적용 이월 + 촉매사 입고','평소 사용하는 기본값','전월 말 적송재고 PDF의 이월 + 희성 출하 원본 또는 유미코아 Summary의 당월 납품 수량','PDF 이월 10 + 촉매사 입고 90 = 100개','이월 수정이 저장돼 있으면 수정한 이월을 사용합니다.'],
  ['장부 이월 + ERP 입고','기존 보고서의 이월 장부를 기준으로 계산하기로 확인한 경우','추가 비교 자료로 등록한 기존 보고서의 전월 이월 + ERP 촉매 입고 수량','장부 이월 8 + ERP 입고 90 = 98개','‘장부’는 ERP 입고 파일이 아닙니다. 기존 보고서 미정산 비교 자료와 ERP 입고가 모두 필요합니다.'],
  ['전월 확정 미마감 + 촉매사 입고','이 프로그램에서 확정한 전월 미마감을 이어서 계산할 경우','연결한 전월 확정본의 미마감 + 촉매사의 당월 입고','전월 확정 미마감 6 + 촉매사 입고 90 = 96개','‘확정·출력 → 백업·재작업·전월 이월 연결’에서 사용할 전월 확정본을 먼저 연결해야 합니다.'],
  ['근거에 따른 별도 구성','앞의 세 가지로 처리할 수 없는 정정 근거가 있을 경우','이 화면에서 직접 적은 전월 이월 + 당월 입고','확인된 이월 8 + 확인된 입고 92 = 100개','이 선택을 하면 두 수량 입력칸이 나타납니다. 차이를 없애려고 임의로 맞추지 말고 정정 자료를 근거로 적습니다.'],
] as const;

export function AdjustmentGuideContent({topic}:{topic:AdjustmentTopic}){
  const help=adjustmentTopics[topic];
  return <div className="adjustment-guide-content">
    <h2>{help.title} — 무슨 뜻인가요?</h2><p className="adjustment-meaning">{help.meaning}</p>
    <h3>언제 사용하나요?</h3><p>{help.when}</p>
    <div className="adjustment-example"><strong>숫자로 보면</strong><p>{help.example}</p><small>설명용 숫자이며 현재 품목의 실제 수량이 아닙니다.</small></div>
    {topic==='source'&&<><h3>‘적용 구성’ 네 가지는 이렇게 다릅니다</h3><p>‘구성’은 <strong>이월과 입고를 어떤 자료에서 가져올지</strong>라는 뜻입니다. 네 가지를 모두 입력하는 것이 아니라 한 가지를 고릅니다.</p><div className="adjustment-choices">{choices.map(([title,when,from,example,note])=><section key={title}><h4>{title}</h4><p><strong>쓰는 경우:</strong> {when}</p><p><strong>가져올 수량:</strong> {from}</p><p className="adjustment-choice-example">{example}</p><p>{note}</p></section>)}</div></>}
    <h3>어떻게 입력하나요?</h3><ol>{help.steps.map(step=><li key={step}>{step}</li>)}</ol>
    <h3>저장하면 무엇이 바뀌나요?</h3><p>{help.result}</p><p className="adjustment-note">{help.note}</p>
    <p>아래 ‘변경 사유’에는 바꾸는 이유를, ‘근거’에는 확인한 파일명·시트·행·전표 등을 적습니다. 설명 창을 여는 것만으로 수량이나 선택값이 저장되지는 않습니다.</p>
  </div>;
}

export function AdjustmentHelp({topic,label}:{topic:AdjustmentTopic;label:string}){
  const dialog=useRef<HTMLDialogElement>(null), trigger=useRef<HTMLButtonElement>(null), id=useId();
  return <><button ref={trigger} type="button" className="adjustment-help-button" aria-haspopup="dialog" aria-controls={id} onClick={()=>dialog.current?.showModal()}>{label}</button>
    {createPortal(<dialog id={id} ref={dialog} className="adjustment-help-dialog" aria-label={`${adjustmentTopics[topic].title} 가이드`} onClose={()=>trigger.current?.focus()} onClick={e=>{if(e.target===e.currentTarget)dialog.current?.close()}}>
      <div className="adjustment-help-header"><strong>추가 조정 사용 가이드</strong><button type="button" autoFocus onClick={()=>dialog.current?.close()}>설명 닫기</button></div>
      <AdjustmentGuideContent topic={topic}/>
    </dialog>,document.body)}</>;
}
