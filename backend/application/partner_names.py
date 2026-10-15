"""Exact known supplier aliases; never fuzzy-match business names."""
from backend.domain.errors import WorkflowError

SUPPLIER_ALIASES = {
    '희성': '희성', '희성촉매': '희성', '희성촉매(주)': '희성', '(주)희성촉매': '희성',
    '유미코아': '유미코아', '한국유미코아': '유미코아', '한국유미코아촉매': '유미코아',
    '한국유미코아촉매(주)': '유미코아', '(주)한국유미코아촉매': '유미코아',
}


def supplier_name(value):
    return SUPPLIER_ALIASES.get(value.strip()) if isinstance(value, str) else None


def selected_supplier(value):
    name = supplier_name(value)
    if name is None:
        raise WorkflowError('SUPPLIER_SELECTION', '촉매사는 목록에서 희성 또는 유미코아를 선택해 주세요.')
    return name


def customer_options(records):
    return sorted({r['evidence']['_normalized']['value'].get('customer', '').strip()
                   for r in records if r['evidence']['_normalized']['value'].get('customer', '').strip()})
