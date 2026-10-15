"""Content-scoped dependency hashes, separate from whole-file audit identities."""
import hashlib
import json


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()


def parser_rule(batch):
    # A reread candidate's random suffix identifies its audit version, not a
    # change to the reader or to the part's extracted evidence.
    return (batch.get('parser_version') or '').split('-reread-', 1)[0]


def record_content(batch, row):
    # Moving an unchanged row, or replacing a file to edit another part, must
    # not invalidate this part. Full file IDs/hashes/locations remain in audit refs.
    if parser_rule(batch)=='program-master-1':
        return {'parser':'program-master-1','part':row['part'],'quantity':row['quantity'],
                'definition':row['evidence']['_normalized']['value']}
    cells = []
    for key, value in row['evidence'].items():
        if key == 'pdf':
            value = {k: v for k, v in value.items() if k not in ('box', 'page')}
        cells.append(value)
    return {'period': batch.get('source_period'), 'parser': parser_rule(batch),
            'sheet': row['sheet'], 'part': row['part'], 'quantity': row['quantity'],
            'cells': sorted(cells, key=digest)}


def scoped_evidence(value, sources):
    """Resolve route references to the relevant original row, without batch IDs."""
    index = {b['id']: (role, b, {r['ordinal']: r for r in b['records']}) for role, b in sources.items()}

    def walk(item):
        if isinstance(item, list):
            return sorted((walk(v) for v in item), key=digest)
        if not isinstance(item, dict):
            return item
        if 'batch_id' in item and 'ordinal' in item:
            role, batch, records = index[item['batch_id']]
            return {'role': role, 'record': record_content(batch, records[item['ordinal']]),
                    'selection': {k: v for k, v in item.items() if k in ('metric', 'quantity', 'warehouse')}}
        return {k: walk(v) for k, v in item.items()}
    return walk(value)
