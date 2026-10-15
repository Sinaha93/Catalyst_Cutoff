"""Selectable names only; never rewrite a master, monthly decision or snapshot."""
import json
import unicodedata
from backend.adapters.storage import now
from backend.domain.errors import WorkflowError

CATEGORIES = ('customer', 'path', 'plant', 'destination', 'warehouse')


class Choices:
    def __init__(self, store): self.store = store

    def read(self, conn=None):
        if conn is None:
            with self.store.connect() as connection:
                return self.read(connection)
        names = {k: {} for k in CATEGORIES}

        def add(category, name, origin):
            if isinstance(name, str) and name.strip():
                name = name.strip()
                names[category].setdefault(name, {'name': name, 'active': True, 'origin': origin})

        def collect(n, role):
            if role == 'bom_master': add('customer', n.get('customer'), '등록 BOM')
            if role == 'route_master':
                for k in ('path', 'plant'): add(k, n.get(k), '등록 경로')
                destination = n.get('destination', '')
                for line in destination.splitlines():
                    add('destination', line.split(':', 1)[-1], '등록 경로')
                for name in n.get('warehouses', []): add('warehouse', name, '등록 경로')
            if role in ('product_stock', 'semi_stock'): add('warehouse', n.get('warehouse'), '사용 중인 수불 원본')

        # Registered versions and selected source files are evidence, not guesses
        # from ERP's provisional closing customer.
        for row in conn.execute("SELECT role,payload_json FROM master_version WHERE role IN ('bom_master','route_master')"):
            for record in json.loads(row['payload_json']).get('records', []):
                collect(record.get('evidence', {}).get('_normalized', {}).get('value', {}), row['role'])
        for row in conn.execute('''SELECT DISTINCT b.role,r.evidence_json FROM draft_source s
            JOIN import_batch b ON b.id=s.batch_id JOIN source_record r ON r.batch_id=b.id
            WHERE b.role IN ('bom_master','route_master','product_stock','semi_stock')'''):
            collect(json.loads(row['evidence_json']).get('_normalized', {}).get('value', {}), row['role'])
        revision = 0
        for row in conn.execute('SELECT * FROM choice_event ORDER BY id'):
            revision = row['id']
            add(row['category'], row['name'], '직접 등록')
            names[row['category']][row['name']]['active'] = bool(row['active'])
        return {'revision': revision, 'categories': {k: sorted(v.values(), key=lambda x: x['name']) for k,v in names.items()}}

    def active(self, category):
        return [r['name'] for r in self.read()['categories'][category] if r['active']]

    def save(self, category, name, active, expected_revision):
        name = unicodedata.normalize('NFC', name.strip())
        if category not in CATEGORIES or not name or len(name)>200 or any(ord(c)<32 for c in name) or ':' in name:
            raise WorkflowError('CHOICE_NAME', '목록 종류와 이름을 확인해 주세요. 줄바꿈·콜론은 사용할 수 없습니다.')
        with self.store.connect(write=True) as conn:
            before = self.read(conn)
            if before['revision'] != expected_revision:
                raise WorkflowError('CHOICE_CONFLICT', '선택 목록이 변경되었습니다. 목록을 새로 읽고 다시 저장해 주세요.', 409)
            old = next((r for r in before['categories'][category] if r['name']==name), None)
            if old is None and not active:
                raise WorkflowError('CHOICE_NOT_FOUND', '등록된 이름을 선택해 주세요.')
            if old is None or old['active'] != active:
                conn.execute('INSERT INTO choice_event(category,name,active,created_at) VALUES(?,?,?,?)', (category,name,int(active),now()))
            return self.read(conn)
