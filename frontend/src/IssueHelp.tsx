import {useId,useRef} from 'react';
import {createPortal} from 'react-dom';
import type {Page} from './navigation';
import type {AdjustmentTopic} from './AdjustmentHelp';
import {closingTerms} from './closingTerms';
import './adjustmentHelp.css';

export type HelpTarget={page:Page;masterRole?:'bom_master'|'route_master'|'price_master';adjustment?:AdjustmentTopic;evidence?:'basis'|'reconciliation';part?:string;partKind?:'product'|'catalyst';supplier?:string;sourceRoles?:string[];products?:string[];issueCode?:string;maintenance?:boolean};
export type HelpRequest={id:number;target:HelpTarget};
type Action={label:string;target:HelpTarget};
type Help={title:string;meaning:string;steps:string[];note:string;actions:Action[]};
const bom:Action={label:'BOM 관리로 이동',target:{page:'masters',masterRole:'bom_master'}};
const routes:Action={label:'경로·공장 관리로 이동',target:{page:'masters',masterRole:'route_master'}};
const sources:Action={label:'자료 등록으로 이동',target:{page:'sources'}};
const basis:Action={label:'제품 납품·BOM 연결 확인',target:{page:'review/evidence',evidence:'basis'}};
const adjust=(kind:AdjustmentTopic,label:string):Action=>({label,target:{page:'review',adjustment:kind}});
const holds:Action={label:'미마감 조정으로 이동',target:{page:'review/hold'}};
const compare:Action={label:'촉매사·ERP 수량 대조',target:{page:'review/evidence',evidence:'reconciliation'}};

export const issueGuides:Record<string,Help>={
 mapping:{title:'입고는 있지만 제품·마감처 연결이 없어요',meaning:'촉매 수량은 읽었지만 이 촉매가 어느 제품에 들어가고 어디로 납품되는지 연결하지 못했습니다.',
  steps:['이 촉매가 들어가는 정확한 제품 품번과 제품 1개당 촉매 소요량을 확인합니다.','아래 BOM 관리로 이동을 누르면 해당 촉매 품번이 채워진 품목 추가 화면이 열립니다. 제품 품번·소요량·촉매사를 확인하고 BOM 저장·이번 달 적용을 누릅니다. 기존 제품이면 기존 촉매를 유지하면서 추가합니다.','경로·공장 관리로 이동하면 연결된 제품의 경로가 준비됩니다. 여러 경로이면 수정할 것을 선택한 뒤 값을 고치고 수정 저장·이번 달 적용을 누릅니다.','마감 검토로 돌아와 전체 다시 계산을 누르고 해당 촉매의 마감처와 수량을 확인합니다.'],
  note:'ERP 입고 때 적은 거래처만으로 마감처를 정하지 않습니다. BOM을 사용하지 않는 직사급 등은 확인된 별도 납품 근거가 있을 때만 ‘이번 달 마감처 연결’을 사용합니다.',actions:[bom,routes,basis,adjust('mapping','이번 달 마감처 연결')]},
 basis:{title:'제품 납품·BOM·경로 근거가 부족해요',meaning:'촉매를 공장별로 나눌 때 필요한 제품 연결이나 납품 수량이 완성되지 않았습니다.',
  steps:['제품 납품·BOM 연결에서 문제가 표시된 제품과 경로를 확인합니다.','BOM 누락은 BOM 관리, 창고·마감처·집계 방법 누락은 경로·공장 관리에서 보완합니다.','제품·반제품 수불이나 글로비스 실제 입고 파일이 빠졌으면 자료 등록에서 이번 달 원본으로 사용합니다.','같은 제품 수량을 여러 공장으로 구분해야 하는 경우에는 제품 수량 구분에 납품 근거 수량을 입력합니다.'],
  note:'비슷한 품번을 임의로 대신 연결하거나 같은 이동 수량을 여러 창고에서 중복 집계하지 않습니다.',actions:[basis,bom,routes,sources,adjust('splits','제품 수량 구분으로 이동')]},
 masters:{title:'이번 달에 사용할 기준을 적용해 주세요',meaning:'BOM 또는 경로 기준이 이번 달 계산에 연결되지 않아 계산을 시작할 수 없습니다.',
  steps:['기준 관리에서 BOM과 경로·공장 카드의 상태를 확인합니다.','이미 저장된 기준이 있으면 버전 선택 → 이번 달 적용 전 차이 보기 → 이 버전을 이번 달에 적용 순서로 진행합니다.','등록된 기준이 없으면 기준 파일을 읽고 비교·저장한 다음 이번 달에 적용합니다.'],
  note:'파일 등록·버전 저장과 이번 달 적용은 다른 단계입니다. 카드에 ‘✓ 이번 달 사용’이 표시되는지 확인합니다.',actions:[bom,routes]},
 sources:{title:'계산에 필요한 원본을 확인해 주세요',meaning:'필수 자료가 없거나, 등록한 자료를 이번 달 계산에 사용하도록 선택하지 않았습니다.',
  steps:['자료 등록에서 촉매사 출하·납품, 전월 적송 PDF, ERP 촉매 입고 등의 상태를 확인합니다.','빠진 파일을 원본 보관·읽기로 등록합니다. 확인할 항목이 있으면 원본과 대조해 처리합니다.','이번 달 원본으로 사용을 누르고 마감 검토에서 다시 계산합니다.'],
  note:'파일이 없는 것과 그 파일에 해당 품번의 거래가 0개인 것은 다릅니다. 10월 마감의 적송 PDF는 9월 말 자료입니다.',actions:[sources]},
 difference:{title:'자료별 이월·입고 수량이 달라요',meaning:'촉매사, ERP 또는 전월 확정본에 실제 수량 차이가 있어 어느 자료를 사용할지 확인해야 합니다.',
  steps:['촉매사·ERP 수량 대조 또는 품목의 원천 구성·근거 보기에서 차이가 난 수량을 확인합니다.','조회 기간, 반품, 누락 입고, 이월 정정 등 원인을 확인합니다. 원본이 잘못됐으면 수정본을 등록합니다.','차이의 이유가 확인됐으면 계산 기준 확인에서 사용할 구성을 고르고 사유·근거와 함께 저장합니다.'],
  note:'예: PDF 이월 10개와 장부 이월 8개가 다르면 어느 값이 맞는지 확인합니다. 미마감을 임의로 넣어 차이를 없애지 않습니다.',actions:[compare,adjust('source','계산 기준 확인으로 이동'),sources]},
 hold:{title:'미마감 수량을 다시 확인해 주세요',meaning:'실제 입고 조건이나 저장한 미마감 때문에 이번 달에 남길 수량을 확인해야 합니다.',
  steps:['품목의 이월·입고·미마감과 실제 납품 근거를 확인합니다. 글로비스는 실제 제품 입고 × BOM 수량만 마감할 수 있습니다.','미마감 조정에서 이번 달 추가 미마감과 전월 물량 중 이번 달 마감할 수량을 확인하고 수정합니다.','사유·근거를 적어 저장하고 마감 합계와 검산 차이를 확인합니다.'],
  note:'일반 품목은 별도 미마감 입력이 없으면 이월 + 입고를 전량 마감합니다. 이미 입력한 미마감이나 글로비스 조건은 계속 적용됩니다.',actions:[holds,sources,basis]},
 prices:{title:'적용할 단가가 없거나 확인이 필요해요',meaning:'마감 또는 미마감 금액을 계산할 단가를 결정하지 못했습니다.',
  steps:['촉매 단가 관리로 이동하면 해당 품번과 기존 단가가 채워집니다. 미등록 품번은 단가만 입력할 수 있게 준비됩니다.','기본 단가와 변경 사유를 입력하고 수정 저장·이번 달 적용을 누릅니다.','이번 달에만 다른 가격이나 가단가를 사용할 경우 해당 품목의 단가 조정에서 마감처별 가격·단가 구분·사유·근거를 저장합니다.'],
  note:'단가를 고치면 금액을 다시 계산합니다. 촉매 수량을 바꾸는 메뉴는 아닙니다.',actions:[{label:'촉매 단가 관리로 이동',target:{page:'masters',masterRole:'price_master'}},adjust('prices','이 품목의 이번 달 단가 수정')]},
 quantities:{title:'공장별 합계와 전체 수량이 맞지 않아요',meaning:'공장별로 수정한 마감 수량의 합계가 이월 + 입고 − 미마감 수량과 다릅니다.',
  steps:['품목의 전체 수량과 미마감을 먼저 확인합니다.','공장별 수량 조정에서 자동 계산과 수정 수량을 비교하고 납품 근거에 맞게 고칩니다.','검산 차이가 0이 되는지 확인합니다. 자동 계산으로 돌아가려면 해당 공장의 입력값을 비우고 저장합니다.'],
  note:'한 공장을 수정해도 다른 공장 수량이 자동으로 바뀌지는 않습니다. 글로비스 실제 입고 수량은 임의로 줄이지 않습니다.',actions:[{label:'공장별 수량 조정으로 이동',target:{page:'review/quantities'}},holds]},
 statement:{title:'유미코아 원문의 마감 수량과 달라요',meaning:'유미코아 원문 마감 수량과 프로그램에서 계산한 마감 수량이 다릅니다.',
  steps:['이월·입고·미마감과 유미코아 원문 수량을 대조합니다.','계산이 잘못됐다면 원인인 원본 또는 미마감 수량을 먼저 수정합니다.','계산 결과가 맞고 원문과 달라야 하는 사유가 있으면 촉매사 마감 차이 확인에 이유와 근거를 저장합니다.'],
  note:'차이 확인은 수량을 바꾸는 기능이 아닙니다. 예를 들어 원문 100개 중 실제 미마감 10개라면 먼저 미마감을 반영해 90개로 계산합니다.',actions:[holds,adjust('statement','촉매사 마감 차이 확인으로 이동')]},
 previous:{title:'연결한 전월 확정본을 확인해 주세요',meaning:'전월이 다시 확정됐거나 이월 연결을 확인해야 합니다. 기존 연결은 자동으로 교체하지 않습니다.',
  steps:['확정·출력의 백업·재작업·전월 이월 연결을 펼쳐 연결된 버전과 새 버전을 확인합니다.','이번 달에 사용할 전월 확정본을 확인해 연결합니다.','촉매사 PDF 이월과 차이가 있으면 계산 기준 확인에서 근거를 선택하고 다시 검토합니다.'],
  note:'새 전월 확정본을 연결하면 관련 계산과 조정을 다시 확인해야 할 수 있습니다.',actions:[{label:'전월 이월 연결로 이동',target:{page:'final',maintenance:true}},adjust('source','계산 기준 확인으로 이동')]},
 generic:{title:'표시된 원인부터 확인해 주세요',meaning:'이 메시지는 아래 원본 또는 계산 근거에서 상세 원인을 확인해야 합니다.',
  steps:['표시된 품번과 메시지를 확인합니다.','계산 근거에서 관련 원본·수량·연결을 확인하고 해당 자료를 보완합니다.','저장 후 마감 검토에서 다시 계산합니다. 연결 오류라면 입력값을 보존한 채 프로그램 실행 상태부터 확인합니다.'],
  note:'수량을 임의로 바꿔 경고를 없애지 않습니다. 입력 중인 내용은 저장하거나 작성 취소한 뒤 다른 화면으로 이동합니다.',actions:[basis,sources]},
};

export function issueGuide(code:string):Help{
 if(code.endsWith('_stale')){
  const kind=code.slice(0,-6);
  const action=kind==='hold'?holds:kind==='quantities'?issueGuides.quantities.actions[0]:adjust((['carry','source','prices','mapping','splits','statement'].includes(kind)?kind:kind==='split'?'splits':'source') as AdjustmentTopic,'해당 조정 다시 확인');
  return {title:'수정에 사용한 원본이 바뀌었어요',meaning:'예전에 저장한 조정값의 근거가 바뀌어 그대로 적용하지 않고 확인을 기다립니다.',steps:['변경된 원본·기준과 이전 조정 내용을 비교합니다.','수정 화면에서 현재 값과 사유·근거를 확인해 다시 저장합니다.','이전 조정이 더 이상 필요 없다면 저장된 수정값 해제를 사용합니다.'],note:'이전 값이 맞더라도 바뀐 근거에 적용할 수 있는지 확인해야 합니다.',actions:[action,basis]};
 }
 const groups:Record<string,string>={mapping_missing:'mapping',unmapped_product:'basis',basis_incomplete:'basis',weight_required:'basis',basis_kind_conflict:'basis',MASTER_REQUIRED:'masters',source_missing:'sources',SOURCE_NOT_READY:'sources',supplier_required:'sources',supplier_conflict:'sources',source_difference:'difference',negative_available:'difference',hold_required:'hold',hold_exceeds:'hold',pool_conflict:'hold',pool_required:'hold',actual_exceeds_pool:'hold',actual_receipts_missing:'hold',price_required:'prices',pending_price_required:'prices',balance_difference:'quantities',umicore_closing_difference:'statement',previous_version_changed:'previous'};
 return issueGuides[groups[code]??'generic'];
}
export function issueMessage(code:string,message:string){return code==='mapping_missing'?'입고 수량은 있지만 연결된 제품·마감처가 없습니다. BOM과 납품 경로를 확인해 주세요.':closingTerms(message)}

export function IssueGuideContent({help,part,partKind,supplier,sourceRoles,products,issueCode,blocked,onNavigate}:{help:Help;part?:string;partKind?:'product'|'catalyst';supplier?:string;sourceRoles?:string[];products?:string[];issueCode?:string;blocked:boolean;onNavigate:(target:HelpTarget)=>void}){
 return <div className="adjustment-guide-content"><h2>{help.title}</h2>{part&&part!=='*'&&<p><strong>확인할 품번: {part}</strong></p>}<p className="adjustment-meaning">{help.meaning}</p><h3>이 순서로 처리하세요</h3><ol>{help.steps.map(s=><li key={s}>{s}</li>)}</ol><p className="adjustment-note">{help.note}</p><h3>수정할 화면 바로 열기</h3><div className="issue-help-actions">{help.actions.map(action=><button key={action.label} type="button" disabled={blocked} onClick={()=>onNavigate({...action.target,part,partKind,supplier,sourceRoles,products,issueCode})}>{action.label} →</button>)}</div>{blocked&&<p>작성 중인 내용이 있으면 설명을 닫고 저장하거나 작성 취소한 뒤 이동해 주세요. 처리 중이면 완료 후 이동할 수 있습니다.</p>}<p>이동하면 관련 입력 화면이 준비됩니다. 입력값을 확인하고 저장해야 실제 반영됩니다.</p></div>;
}
export function IssueHelp({code,message,part,supplier,sourceRoles,products,blocked,onNavigate}:{code:string;message:string;part?:string;supplier?:string;sourceRoles?:string[];products?:string[];issueCode?:string;blocked:boolean;onNavigate:(target:HelpTarget)=>void}){
 const dialog=useRef<HTMLDialogElement>(null),button=useRef<HTMLButtonElement>(null),id=useId();const help=issueGuide(code);
 const relatedSources=sourceRoles??(code==='actual_receipts_missing'||(code==='hold_required'&&message.includes('글로비스'))?['glovis_receipts']:['supplier_conflict','supplier_required'].includes(code)?['heesung_shipments','umicore_statement']:code==='source_difference'?['erp_receipts',...(supplier==='희성'?['heesung_carryover','heesung_shipments']:supplier==='유미코아'?['umicore_carryover','umicore_statement']:[])]:['basis_incomplete','weight_required','basis_kind_conflict'].includes(code)?['product_stock','semi_stock','glovis_receipts']:undefined);
 return <><button ref={button} type="button" className="adjustment-help-button" aria-haspopup="dialog" aria-controls={id} onClick={()=>dialog.current?.showModal()}>해결 방법</button>{createPortal(<dialog id={id} ref={dialog} className="adjustment-help-dialog" aria-label="확인 항목 해결 가이드" onClose={()=>{if(document.activeElement===document.body)button.current?.focus()}}><div className="adjustment-help-header"><strong>확인 항목 해결 가이드</strong><button type="button" autoFocus onClick={()=>dialog.current?.close()}>설명 닫기</button></div><div className="issue-original-message">{issueMessage(code,message)}</div><IssueGuideContent help={help} part={part} supplier={supplier} partKind={part&&part!=='*'?(code==='unmapped_product'?'product':'catalyst'):undefined} sourceRoles={relatedSources} products={code==='unmapped_product'&&part?[part]:products} issueCode={code} blocked={blocked} onNavigate={target=>{dialog.current?.close();onNavigate(target)}}/></dialog>,document.body)}</>;
}
