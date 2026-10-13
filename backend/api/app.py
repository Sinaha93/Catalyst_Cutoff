import secrets
import sqlite3
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import BackgroundTasks, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field

from backend.adapters.lock import WorkspaceLock
from backend.adapters.storage import SCHEMA_VERSION, Store
from backend.application.workflow import Workflow
from backend.domain.errors import WorkflowError


class StartInput(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    month: str


class SaveInput(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    expected_revision: int = Field(ge=1)
    note: str = Field(max_length=10000)


def create_app(data_dir: Path, static_dir: Path | None = None, on_ready=None, on_shutdown=None):
    store = Store(data_dir)
    workflow = Workflow(store)
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
        return {'token': token, 'data_dir': str(store.root), 'schema_version': SCHEMA_VERSION, 'stage': 'W1'}

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
