const aliases:Record<string,string>={'희성':'희성','희성촉매':'희성','희성촉매(주)':'희성','(주)희성촉매':'희성','유미코아':'유미코아','한국유미코아':'유미코아','한국유미코아촉매':'유미코아','한국유미코아촉매(주)':'유미코아','(주)한국유미코아촉매':'유미코아'};
export function supplierName(value:string){return aliases[value.trim()]??value}
export function SupplierSelect({value,onChange}:{value:string;onChange:(v:string)=>void}){
 const selected=supplierName(value),unknown=Boolean(selected)&&!['희성','유미코아'].includes(selected);
 return <select aria-label="촉매사" value={selected} onChange={e=>onChange(e.target.value)}><option value="">선택하세요</option>{unknown&&<option value={selected} disabled>{value} · 기존 값 확인 필요</option>}<option value="희성">희성</option><option value="유미코아">유미코아</option></select>;
}
