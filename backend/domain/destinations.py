"""Reviewed spelling aliases only; factories and logistics paths stay separate."""
ALIASES = {'현대위아':'현대 위아', '현대모비스':'현대 모비스', '현대모비스(주)':'현대 모비스', '글로비스':'현대 글로비스'}


def canonical_destination(value):
    return ALIASES.get(value, value)
