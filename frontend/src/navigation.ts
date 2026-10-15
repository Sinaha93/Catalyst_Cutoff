export const pages = {
  workspace: {label:'월 작업', group:'workspace', hint:'마감월을 선택하고 작업을 이어갑니다.'},
  sources: {label:'자료 등록', group:'sources', hint:'이번 달 계산에 사용할 원본 자료를 등록합니다.'},
  review: {label:'전체 검토', group:'review', hint:'품목별 계산 결과와 확인할 내용을 검토합니다.'},
  'review/hold': {label:'미마감 조정', group:'review', hint:'이번 달에 남기거나 전월 미마감 중 마감할 수량을 조정합니다.'},
  'review/quantities': {label:'공장별 수량 조정', group:'review', hint:'자동 배분 결과를 확인하고 공장별 마감 수량을 조정합니다.'},
  'review/evidence': {label:'계산 근거', group:'review', hint:'자료 간 차이와 제품 납품·BOM·단가 근거를 확인합니다.'},
  final: {label:'확정·출력', group:'final', hint:'검토한 결과를 확정하고 엑셀로 저장합니다.'},
  masters: {label:'기준 관리', group:'masters', hint:'물류 경로·공장, BOM 버전과 단가 예외를 관리합니다.'},
  guide: {label:'사용 가이드', group:'guide', hint:'실제 화면을 보면서 월 마감을 차례대로 따라 하세요.'},
} as const;
export type Page = keyof typeof pages;
export const mainMenu = [['workspace','월 작업'],['sources','자료 등록'],['review','마감 검토'],['final','확정·출력'],['masters','기준 관리'],['guide','사용 가이드']] as const;
export const reviewMenu = [['review','전체 검토'],['review/hold','미마감 조정'],['review/quantities','공장별 수량 조정'],['review/evidence','계산 근거']] as const;
export function pageFromHash():Page {const key=window.location.hash.slice(1);return Object.hasOwn(pages,key)?key as Page:'workspace'}
