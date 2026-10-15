"""Explicit reset of one master family; finals and other active months protect it."""
import json
from backend.application.dependencies import digest
from backend.application.imports import Imports
from backend.adapters.storage import now
from backend.domain.errors import WorkflowError

LABELS={'bom_master':'BOM','price_master':'촉매 단가','route_master':'경로·공장'}

def file_ids(value):
    result=set()
    if isinstance(value,dict):
        if value.get('file_id'):result.add(value['file_id'])
        for child in value.values():result.update(file_ids(child))
    elif isinstance(value,list):
        for child in value:result.update(file_ids(child))
    return result

class MasterReset:
    def __init__(self,store):self.store=store

    def state(self,conn,month,role):
        if role not in LABELS:raise WorkflowError('MASTER_ROLE','BOM·촉매 단가·경로 중 초기화할 기준을 선택해 주세요.')
        d=self.store.read(conn,month)
        versions=[dict(r) for r in conn.execute('SELECT * FROM master_version WHERE role=? ORDER BY version',(role,))]
        batches=[dict(r) for r in conn.execute('SELECT id,file_id FROM import_batch WHERE role=? ORDER BY id',(role,))]
        ids={r['file_id'] for r in batches}
        for r in versions:ids.update(file_ids(json.loads(r['payload_json'])))
        files=[dict(r) for r in conn.execute('SELECT * FROM source_file') if r['id'] in ids]
        blocked=set()
        for r in conn.execute("""SELECT DISTINCT d.month FROM draft d WHERE d.status='active' AND d.month<>?
            AND (EXISTS(SELECT 1 FROM draft_master m WHERE m.draft_id=d.id AND m.role=?)
              OR EXISTS(SELECT 1 FROM draft_source s WHERE s.draft_id=d.id AND s.role=?))""",(month,role,role)):
            blocked.add(r['month']+' 작업에서 사용 중')
        for r in conn.execute('SELECT month,version,payload_json FROM closing_snapshot'):
            data=json.loads(r['payload_json'])
            if role in data.get('sources',{}) or role in data.get('frozen_evidence',{}):
                blocked.add(f"{r['month']} 확정 v{r['version']}에서 사용 중")
        summary={'role':role,'label':LABELS[role],'revision':d['revision'],'version_count':len(versions),
                 'source_count':len(batches),'file_count':len(files),'blocked':sorted(blocked)}
        summary['fingerprint']=digest({'summary':summary,'versions':versions,'batches':batches,'files':files})
        return summary,d,files

    def preview(self,month,role):
        with self.store.connect() as conn:return self.state(conn,month,role)[0]

    def reset(self,month,role,revision,fingerprint,confirmation):
        paths=[]
        with self.store.connect(write=True) as conn:
            state,before,files=self.state(conn,month,role);Imports.revision(before,revision)
            if confirmation!=LABELS[role]+' 초기화':raise WorkflowError('MASTER_RESET_CONFIRM','초기화할 기준을 확인해 주세요.')
            if state['fingerprint']!=fingerprint:raise WorkflowError('MASTER_RESET_CHANGED','등록된 기준이 변경됐습니다. 초기화 범위를 다시 확인해 주세요.',409)
            if state['blocked']:raise WorkflowError('MASTER_IN_USE','초기화할 수 없습니다: '+', '.join(state['blocked']),409)
            for f in files:
                path=(self.store.root/f['relative_path']).resolve()
                if not path.is_relative_to((self.store.root/'originals').resolve()):raise WorkflowError('DELETE_PATH','보관 원본 경로가 올바르지 않아 초기화하지 않았습니다.',409)
            conn.execute('DELETE FROM draft_master WHERE role=?',(role,))
            conn.execute('DELETE FROM draft_source WHERE role=?',(role,))
            conn.execute("""DELETE FROM source_selection_event WHERE batch_id IN(SELECT id FROM import_batch WHERE role=?)
                OR previous_batch_id IN(SELECT id FROM import_batch WHERE role=?)""",(role,role))
            for table in ('source_review','source_record'):
                conn.execute(f'DELETE FROM {table} WHERE batch_id IN(SELECT id FROM import_batch WHERE role=?)',(role,))
            conn.execute('DELETE FROM import_batch WHERE role=?',(role,))
            trigger=conn.execute("SELECT sql FROM sqlite_master WHERE type='trigger' AND name='immutable_master_delete'").fetchone()
            if trigger:conn.execute('DROP TRIGGER immutable_master_delete')
            conn.execute('DELETE FROM master_version WHERE role=?',(role,))
            if trigger:conn.execute(trigger[0])
            protected=set()
            for r in conn.execute('SELECT payload_json FROM master_version UNION ALL SELECT payload_json FROM closing_snapshot'):
                protected.update(file_ids(json.loads(r[0])))
            for f in files:
                if f['id'] not in protected and not conn.execute('SELECT 1 FROM import_batch WHERE file_id=?',(f['id'],)).fetchone():
                    conn.execute('DELETE FROM source_file WHERE id=?',(f['id'],));paths.append((self.store.root/f['relative_path']).resolve())
            conn.execute('UPDATE draft SET revision=revision+1,updated_at=? WHERE id=?',(now(),before['id']))
            draft=self.store.read(conn,month)
            self.store.audit(conn,{**draft,'master_reset':state},'master_reset',before)
        failed=[]
        for path in paths:
            try:path.unlink(missing_ok=True)
            except OSError:failed.append(path.name)
        return {'draft':draft,'reset':state,'deleted_file_count':len(paths)-len(failed),
                'warning':f'등록은 초기화했습니다. 사용 중인 원본 파일 {len(failed)}개는 지우지 못했습니다.' if failed else None}
