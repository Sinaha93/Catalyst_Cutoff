import hashlib
import json
import os
import re
from pathlib import Path
from uuid import uuid4

from backend.adapters.heesung import PARSER_VERSION, read_shipments
from backend.adapters.carryover_pdf import PARSER_VERSION as PDF_VERSION, read_carryover, render_page
from backend.adapters.storage import now
from backend.application.workflow import Workflow
from backend.domain.errors import WorkflowError

MAX_BYTES = 16 * 1024**2
ROLES = {'heesung_shipments':'.xlsx', 'heesung_carryover':'.pdf'}


class Imports:
    def __init__(self, store):
        self.store = store

    @staticmethod
    def revision(draft, expected):
        if draft['revision'] != expected:
            raise WorkflowError('REVISION_CONFLICT','월 작업이 변경되었습니다. 최신 저장본을 불러온 뒤 다시 등록해 주세요.',409)

    def list(self, month):
        Workflow.validate_month(month)
        with self.store.connect() as conn:
            draft = self.store.read(conn, month)
            batches = [self.describe(row) for row in conn.execute('''SELECT b.*, f.sha256,
                CASE WHEN ds.batch_id=b.id THEN 1 ELSE 0 END AS selected,
                EXISTS(SELECT 1 FROM source_selection_event e WHERE e.batch_id=b.id) AS ever_selected
                FROM import_batch b JOIN source_file f ON f.id=b.file_id
                LEFT JOIN draft_source ds ON ds.draft_id=b.draft_id AND ds.role=b.role
                WHERE b.draft_id=? ORDER BY b.created_at DESC,b.id''',(draft['id'],))]
            for batch in batches:
                review=conn.execute('SELECT review_json FROM source_review WHERE batch_id=? ORDER BY revision DESC LIMIT 1',(batch['id'],)).fetchone()
                if review:
                    data=json.loads(review[0]);batch['result']=data['result'];batch['status']=data['result']['status'];batch['review']=data
            return batches

    @staticmethod
    def describe(row):
        result = dict(row)
        result['result'] = json.loads(result.pop('result_json'))
        return result

    def detail(self, month, batch_id):
        batches = self.list(month)
        batch = next((b for b in batches if b['id']==batch_id),None)
        if batch is None: raise WorkflowError('NOT_FOUND','등록 자료를 찾을 수 없습니다.',404)
        with self.store.connect() as conn:
            batch['records'] = [{**dict(r),'evidence':json.loads(r['evidence_json'])} for r in conn.execute(
                'SELECT ordinal,sheet,row_number,part,quantity,evidence_json FROM source_record WHERE batch_id=? ORDER BY ordinal',(batch_id,))]
            for record in batch['records']: record.pop('evidence_json')
        if 'review' in batch:
            corrections={r['ordinal']:r for r in batch['review']['rows']}
            for r in batch['records']:
                change=corrections[r['ordinal']]
                r['part']=change['part'];r['quantity']=change['quantity']
                r['evidence']['pdf']['reviewed']=change['reviewed']
                r['evidence']['pdf']['peer_quantity']=change['peer_quantity']
        return batch

    def original(self, month, batch_id):
        batch = self.detail(month,batch_id)
        with self.store.connect() as conn:
            row = conn.execute('SELECT * FROM source_file WHERE id=?',(batch['file_id'],)).fetchone()
        path = (self.store.root/row['relative_path']).resolve()
        if not path.is_relative_to(self.store.root/'originals') or not path.is_file():
            raise WorkflowError('ORIGINAL_MISSING','보관된 원본을 찾을 수 없습니다.',404)
        if hashlib.sha256(path.read_bytes()).hexdigest()!=row['sha256']:
            raise WorkflowError('ORIGINAL_CHANGED','보관 원본의 해시가 다릅니다. 백업 원본을 확인해 주세요.',409)
        return path,batch['filename']

    def register(self, month, role, period, filename, expected_revision, content, reread=False):
        Workflow.validate_month(month); Workflow.validate_month(period)
        if role not in ROLES: raise WorkflowError('INVALID_ROLE','지원하는 자료 종류를 선택해 주세요.')
        expected_period = month
        if role=='heesung_carryover':
            year,mon=map(int,month.split('-'));year,mon=(year-1,12) if mon==1 else (year,mon-1)
            expected_period=f'{year:04d}-{mon:02d}'
        if period!=expected_period:
            raise WorkflowError('INVALID_PERIOD',f'이 자료의 기준월은 {expected_period}이어야 합니다.')
        name=filename.replace('\\','/').split('/')[-1].strip()
        if not name or len(name)>200 or any(ord(c)<32 for c in name) or Path(name).suffix.lower()!=ROLES[role]:
            raise WorkflowError('INVALID_FILENAME',f'{ROLES[role]} 원본 파일을 선택해 주세요.')
        if not content or len(content)>MAX_BYTES: raise WorkflowError('FILE_SIZE','빈 파일 또는 16MB를 초과한 파일입니다.')
        digest=hashlib.sha256(content).hexdigest()
        parser=PARSER_VERSION if role=='heesung_shipments' else PDF_VERSION
        if reread: parser+='-reread-'+uuid4().hex
        with self.store.connect() as conn:
            draft=self.store.read(conn,month); self.revision(draft,expected_revision)
            old=conn.execute('''SELECT b.id FROM import_batch b JOIN source_file f ON f.id=b.file_id
                WHERE b.draft_id=? AND f.sha256=? AND b.role=? AND b.source_period=? AND b.parser_version=?''',
                (draft['id'],digest,role,period,parser)).fetchone()
        if old:
            self.original(month,old['id'])
            return {'draft':draft,'batch':self.detail(month,old['id']),'duplicate':True}
        if role=='heesung_shipments':
            result=read_shipments(content,period)
        else:
            if not content.startswith(b'%PDF-'): raise WorkflowError('INVALID_PDF','PDF 원본 형식을 확인해 주세요.')
            result=read_carryover(content,period)
        records=result.pop('records')
        relative=Path('originals')/digest/('source'+ROLES[role]); destination=self.store.root/relative
        destination.parent.mkdir(parents=True,exist_ok=True)
        stage=self.store.root/'staging'/uuid4().hex
        try:
            with stage.open('xb') as stream:
                stream.write(content);stream.flush();os.fsync(stream.fileno())
            if hashlib.sha256(stage.read_bytes()).hexdigest()!=digest:
                raise WorkflowError('COPY_FAILED','원본 복사 검증에 실패했습니다.')
            # Completed content is immutable. A failed DB transaction may leave an
            # unreferenced file; retries reuse it, never delete referenced sources.
            if destination.exists():
                if hashlib.sha256(destination.read_bytes()).hexdigest()!=digest:
                    raise WorkflowError('ORIGINAL_CHANGED','기존 보관 원본이 변경되었습니다. 등록을 중단했습니다.',409)
            else: os.replace(stage,destination)
            with self.store.connect(write=True) as conn:
                before=self.store.read(conn,month); self.revision(before,expected_revision)
                file_id=uuid4().hex
                conn.execute('INSERT OR IGNORE INTO source_file VALUES(?,?,?,?,?)',(file_id,digest,relative.as_posix(),len(content),now()))
                file_id=conn.execute('SELECT id FROM source_file WHERE sha256=?',(digest,)).fetchone()[0]
                batch_id=uuid4().hex
                conn.execute('INSERT INTO import_batch VALUES(?,?,?,?,?,?,?,?,?,?)',
                             (batch_id,before['id'],file_id,name,role,period,parser,result['status'],json.dumps(result,ensure_ascii=False,default=str),now()))
                for i,r in enumerate(records):
                    conn.execute('INSERT INTO source_record VALUES(?,?,?,?,?,?,?)',
                                 (batch_id,i,r['sheet'],r['row_number'],r['part'],r['quantity'],json.dumps(r['evidence'],ensure_ascii=False,default=str)))
                conn.execute('UPDATE draft SET revision=revision+1,updated_at=? WHERE id=?',(now(),before['id']))
                draft=self.store.read(conn,month);self.store.audit(conn,draft,'source_registered',before)
            return {'draft':draft,'batch':self.detail(month,batch_id),'duplicate':False}
        finally:
            stage.unlink(missing_ok=True)

    def reread(self,month,batch_id,expected_revision):
        batch=self.detail(month,batch_id)
        path,name=self.original(month,batch_id)
        return self.register(month,batch['role'],batch['source_period'],name,expected_revision,path.read_bytes(),reread=True)

    def preview(self,month,batch_id,ordinal=None):
        batch=self.detail(month,batch_id)
        if batch['role']!='heesung_carryover': raise WorkflowError('INVALID_ROLE','PDF 자료만 이미지로 볼 수 있습니다.')
        path,_=self.original(month,batch_id)
        image=render_page(path.read_bytes())
        if ordinal is not None:
            row=next((r for r in batch['records'] if r['ordinal']==ordinal),None)
            if row is None: raise WorkflowError('NOT_FOUND','원본 행을 찾을 수 없습니다.',404)
            box=row['evidence']['pdf']['box'];crop=image.crop((round(box[0]*image.width),round(box[1]*image.height),round(box[2]*image.width),round(box[3]*image.height)))
            image.close();image=crop
        from io import BytesIO
        stream=BytesIO();image.save(stream,format='PNG');image.close();return stream.getvalue()

    def review_pdf(self,month,batch_id,expected_revision,rows,printed_total,confirmed_period,reason):
        batch=self.detail(month,batch_id)
        self.original(month,batch_id)
        if batch['role']!='heesung_carryover' or not batch['records']:
            raise WorkflowError('REVIEW_UNAVAILABLE','읽은 PDF 행이 있어야 정정할 수 있습니다.')
        if len(rows)!=len(batch['records']) or {r['ordinal'] for r in rows}!={r['ordinal'] for r in batch['records']}:
            raise WorkflowError('ROW_SET_MISMATCH','원본의 모든 행을 한 번씩 포함해야 합니다.')
        if not re.fullmatch(r'\d{1,12}',printed_total or ''):
            raise WorkflowError('PRINTED_TOTAL_REQUIRED','PDF에 표시된 희성 기준 합계를 입력해 주세요.')
        if confirmed_period!=batch['source_period']:
            raise WorkflowError('PERIOD_CONFIRM_REQUIRED','PDF 본문의 재고 기준월을 확인해 주세요.')
        if not reason.strip():raise WorkflowError('REVIEW_REASON_REQUIRED','인식 정정·확인 내용을 입력해 주세요.')
        issues=[];total=0;parts=[]
        for r in rows:
            for field in ('quantity','peer_quantity'):
                if r[field] in ('',None):r[field]=None
                elif not re.fullmatch(r'\d{1,12}',r[field]):raise WorkflowError('INVALID_QUANTITY','PDF 수량은 0 이상의 정수로 입력해 주세요.')
                else:r[field]=str(int(r[field]))
            r['part']=r['part'].strip().upper()
            valid=bool(re.fullmatch(r'[A-Z0-9]{5}-[A-Z0-9]{5}',r['part'])) and r['quantity'] is not None and r['peer_quantity'] is not None
            if not valid or not r['reviewed']:
                issues.append({'code':'ROW_REVIEW_REQUIRED','location':f"PDF {r['ordinal']+1}행",'message':'품번·양쪽 수량을 확인하고 행 확인을 표시해 주세요.'})
            elif r['quantity']!=r['peer_quantity']:
                issues.append({'code':'PEER_DIFFERENCE','location':f"PDF {r['ordinal']+1}행",'message':'희성과 우신 기준 수량에 차이가 있습니다. 근거 처리가 필요합니다.'})
            if r['quantity'] is not None:total+=int(r['quantity'])
            parts.append(r['part'])
        if len(set(parts))!=len(parts):issues.append({'code':'DUPLICATE_PART','location':'PDF 전체','message':'중복 인식 품번을 원본과 대조해 주세요.'})
        if total!=int(printed_total):issues.append({'code':'TOTAL_MISMATCH','location':'PDF 전체','message':f'행 합계 {total} / PDF 표시 합계 {printed_total}. 차이를 확인해 주세요.'})
        result={'status':'needs_review' if issues else 'ready','issues':issues,'summary':{**batch['result']['summary'],'printed_total':str(int(printed_total)),'quantity_total':str(total),'period_confirmed':True,'quantity_label':'PDF 전월 말 적송재고 (인식 정정·확인)'}}
        with self.store.connect(write=True) as conn:
            before=self.store.read(conn,month);self.revision(before,expected_revision)
            base_batch_id=batch_id
            # Re-reviewing a previously adopted source creates a separate candidate.
            # Existing selections and their evidence never change silently.
            if conn.execute('SELECT 1 FROM source_selection_event WHERE batch_id=?',(batch_id,)).fetchone():
                batch_id=uuid4().hex
                conn.execute('''INSERT INTO import_batch
                    SELECT ?,draft_id,file_id,filename,role,source_period,?,status,result_json,?
                    FROM import_batch WHERE id=?''',(batch_id,PDF_VERSION+'-review-'+batch_id,now(),base_batch_id))
                conn.execute('''INSERT INTO source_record SELECT ?,ordinal,sheet,row_number,part,quantity,evidence_json
                    FROM source_record WHERE batch_id=?''',(batch_id,base_batch_id))
            review={'rows':rows,'result':result,'reason':reason.strip(),'confirmed_period':confirmed_period,'based_on_batch_id':base_batch_id}
            conn.execute('INSERT INTO source_review VALUES(?,?,?,?)',(batch_id,before['revision']+1,json.dumps(review,ensure_ascii=False),now()))
            conn.execute('UPDATE draft SET revision=revision+1,updated_at=? WHERE id=?',(now(),before['id']))
            draft=self.store.read(conn,month);self.store.audit(conn,draft,'source_reviewed',before)
        return {'draft':draft,'batch':self.detail(month,batch_id)}

    def select(self,month,batch_id,expected_revision,previous_batch_id):
        batch=self.detail(month,batch_id)
        self.original(month,batch_id)
        if batch['status']!='ready':
            raise WorkflowError('SOURCE_NOT_READY','자료의 기간·수량·양식 확인을 먼저 완료해야 합니다.',409)
        with self.store.connect(write=True) as conn:
            before=self.store.read(conn,month);self.revision(before,expected_revision)
            row=conn.execute('SELECT batch_id FROM draft_source WHERE draft_id=? AND role=?',(before['id'],batch['role'])).fetchone()
            current=row[0] if row else None
            if current==batch_id: return self.store.read(conn,month)
            if current!=previous_batch_id: raise WorkflowError('SOURCE_CONFLICT','채택 원본이 변경되었습니다. 목록을 다시 불러와 주세요.',409)
            conn.execute('INSERT INTO draft_source VALUES(?,?,?) ON CONFLICT(draft_id,role) DO UPDATE SET batch_id=excluded.batch_id',(before['id'],batch['role'],batch_id))
            conn.execute('INSERT INTO source_selection_event(draft_id,role,previous_batch_id,batch_id,occurred_at) VALUES(?,?,?,?,?)',(before['id'],batch['role'],current,batch_id,now()))
            conn.execute('UPDATE draft SET revision=revision+1,updated_at=? WHERE id=?',(now(),before['id']))
            draft=self.store.read(conn,month);self.store.audit(conn,draft,'source_selected',before)
            return draft
