import secrets
import sqlite3
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import BackgroundTasks, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, FileResponse, Response
from starlette.concurrency import run_in_threadpool
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field

from backend.adapters.lock import WorkspaceLock
from backend.adapters.storage import SCHEMA_VERSION, Store
from backend.application.workflow import Workflow
from backend.application.imports import Imports, MAX_BYTES
from backend.application.basis import Basis
from backend.application.pricing import Pricing
from backend.application.allocation import Allocation
from backend.application.reconciliation import Reconciliation
from backend.application.holds import Holds
from backend.domain.errors import WorkflowError


class StartInput(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    month: str


class SaveInput(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    expected_revision: int = Field(ge=1)
    note: str = Field(max_length=10000)


class HoldLineInput(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    destination: str = Field(min_length=1, max_length=100)
    new_hold: str = Field(max_length=12)
    released: str = Field(max_length=12)
    reason: str = Field(min_length=1, max_length=1000)
    evidence: str = Field(min_length=1, max_length=2000)


class HoldInput(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    expected_revision: int = Field(ge=1)
    fingerprint: str = Field(min_length=64, max_length=64)
    lines: list[HoldLineInput] = Field(min_length=1, max_length=100)


class SelectSourceInput(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    expected_revision: int = Field(ge=1)
    previous_batch_id: str | None = None


class ReviewRow(BaseModel):
    model_config = ConfigDict(extra='forbid',strict=True)
    ordinal: int = Field(ge=0)
    part: str = Field(max_length=80)
    quantity: str | None = Field(max_length=20)
    peer_quantity: str | None = Field(max_length=20)
    reviewed: bool


class ReviewPDFInput(BaseModel):
    model_config = ConfigDict(extra='forbid',strict=True)
    expected_revision: int = Field(ge=1)
    rows: list[ReviewRow] = Field(max_length=40)
    printed_total: str = Field(max_length=20)
    confirmed_period: str = Field(max_length=7)
    reason: str = Field(min_length=1,max_length=1000)


def create_app(data_dir: Path, static_dir: Path | None = None, on_ready=None, on_shutdown=None):
    store = Store(data_dir)
    workflow = Workflow(store)
    imports = Imports(store)
    token = secrets.token_urlsafe(32)

    @asynccontextmanager
    async def lifespan(app):
        with WorkspaceLock(data_dir):
            store.initialize()
            if on_ready:
                on_ready()
            yield

    app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    app.state.store = store

    @app.middleware('http')
    async def local_session(request: Request, call_next):
        if request.url.hostname != '127.0.0.1':
            return JSONResponse({'code': 'INVALID_HOST', 'message': '로컬 주소로 접속해 주세요.'}, status_code=403)
        if request.method not in ('GET', 'HEAD'):
            origin = str(request.base_url).rstrip('/')
            if request.headers.get('origin') != origin or not secrets.compare_digest(request.headers.get('x-session-token', ''), token):
                return JSONResponse({'code': 'INVALID_SESSION', 'message': '프로그램 화면을 새로 열어 주세요. 입력 내용은 먼저 복사해 주세요.'}, status_code=403)
        response = await call_next(request)
        response.headers['Cache-Control'] = 'no-store'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Referrer-Policy'] = 'no-referrer'
        response.headers['Content-Security-Policy'] = "default-src 'self'; style-src 'self'; script-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'"
        return response

    @app.exception_handler(WorkflowError)
    async def workflow_error(_, exc):
        return JSONResponse({'code': exc.code, 'message': exc.message}, status_code=exc.status)

    @app.exception_handler(RequestValidationError)
    async def validation_error(_, exc):
        return JSONResponse({'code': 'INVALID_INPUT', 'message': '입력 형식이나 길이를 확인해 주세요.'}, status_code=422)

    @app.exception_handler(sqlite3.Error)
    async def storage_error(_, exc):
        return JSONResponse({'code': 'STORAGE_FAILED', 'message': '자료 저장소에 접근하지 못했습니다. 입력은 화면에 남아 있습니다. 폴더 권한과 디스크 여유를 확인하고 다시 시도해 주세요.'}, status_code=503)

    @app.get('/api/session')
    def session():
        return {'token': token, 'data_dir': str(store.root), 'schema_version': SCHEMA_VERSION, 'stage': 'W4.3'}

    @app.get('/api/months/{month}/holds')
    def holds_preview(month: str):
        return Holds(store).preview(month)

    @app.post('/api/months/{month}/holds/{part}')
    def save_hold(month: str, part: str, body: HoldInput):
        return Holds(store).save(month,part,body.expected_revision,body.fingerprint,[r.model_dump() for r in body.lines])

    @app.get('/api/months/{month}/reconciliation')
    def reconciliation_preview(month: str):
        return Reconciliation(store).preview(month)

    @app.get('/api/months/{month}/allocation')
    def allocation_preview(month: str):
        return Allocation(store).preview(month)

    @app.get('/api/months/{month}/allocation-template')
    def allocation_template(month: str):
        return Response(Allocation(store).template(month), media_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                        headers={'Content-Disposition': f'attachment; filename="allocation-input-{month}.xlsx"'})

    @app.get('/api/months/{month}/pricing')
    def pricing_preview(month: str):
        return Pricing(store).preview(month)

    @app.get('/api/months/{month}/basis')
    def basis_preview(month: str):
        return Basis(store).preview(month)

    @app.exception_handler(OSError)
    async def file_error(_, exc):
        return JSONResponse({'code':'FILE_STORAGE_FAILED','message':'원본 보관소에 접근하지 못했습니다. 폴더 권한과 디스크 여유를 확인해 주세요. 기존 채택본은 유지됩니다.'},status_code=503)

    @app.get('/api/months/{month}/sources')
    def sources(month: str):
        return imports.list(month)

    @app.get('/api/months/{month}/sources/{batch_id}')
    def source(month: str, batch_id: str):
        return imports.detail(month,batch_id)

    @app.get('/api/months/{month}/sources/{batch_id}/original')
    def original(month: str,batch_id: str):
        path,name=imports.original(month,batch_id)
        return FileResponse(path,filename=name,media_type='application/octet-stream')

    @app.post('/api/months/{month}/sources')
    async def register_source(month: str,request: Request,role: str,source_period: str,filename: str,expected_revision: int,period_confirmed: bool=False):
        content=bytearray()
        async for chunk in request.stream():
            content.extend(chunk)
            if len(content)>MAX_BYTES: raise WorkflowError('FILE_SIZE','원본 파일은 16MB까지 등록할 수 있습니다.',413)
        return await run_in_threadpool(imports.register,month,role,source_period,filename,expected_revision,bytes(content),period_confirmed=period_confirmed)

    @app.post('/api/months/{month}/sources/{batch_id}/select')
    def select_source(month: str,batch_id: str,body: SelectSourceInput):
        return imports.select(month,batch_id,body.expected_revision,body.previous_batch_id)

    @app.post('/api/months/{month}/sources/{batch_id}/reread')
    def reread_source(month:str,batch_id:str,body:SelectSourceInput):
        return imports.reread(month,batch_id,body.expected_revision)

    @app.get('/api/months/{month}/sources/{batch_id}/preview')
    def preview_source(month:str,batch_id:str,ordinal:int|None=None):
        return Response(imports.preview(month,batch_id,ordinal),media_type='image/png')

    @app.post('/api/months/{month}/sources/{batch_id}/review')
    def review_source(month:str,batch_id:str,body:ReviewPDFInput):
        return imports.review_pdf(month,batch_id,body.expected_revision,[r.model_dump() for r in body.rows],body.printed_total,body.confirmed_period,body.reason)

    @app.get('/api/months')
    def months():
        return store.list()

    @app.post('/api/months')
    def start(body: StartInput):
        return workflow.start(body.month)

    @app.get('/api/months/{month}')
    def get_month(month: str):
        return workflow.get(month)

    @app.patch('/api/months/{month}')
    def save(month: str, body: SaveInput):
        return workflow.save(month, body.expected_revision, body.note)

    @app.get('/api/months/{month}/history')
    def history(month: str):
        workflow.validate_month(month)
        return store.history(month)

    @app.post('/api/shutdown')
    def shutdown(tasks: BackgroundTasks):
        if on_shutdown is None:
            raise WorkflowError('SHUTDOWN_UNAVAILABLE', '실행 창에서 종료해 주세요.')
        tasks.add_task(on_shutdown)
        return {'status': 'stopping'}

    if static_dir is not None:
        app.mount('/', StaticFiles(directory=static_dir, html=True), name='frontend')
    return app
