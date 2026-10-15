// Display older saved actions and server messages in the current business terms.
export function closingTerms(text:string){
  return text.replaceAll('보류·해소','미마감 수량 조정')
    .replaceAll('전월 보류','전월 미마감')
    .replaceAll('신규 보류','이번 달 추가 미마감')
    .replaceAll('전부 해소','전월 미마감 전량 마감')
    .replaceAll('일부 해소','전월 미마감 일부 마감')
    .replaceAll('보류 계속','다음 달로 계속 이월')
    .replaceAll('미마감보류','미마감').replaceAll('미마감 보류','미마감')
    .replaceAll('보류','미마감').replaceAll('해소','이월분 마감');
}
