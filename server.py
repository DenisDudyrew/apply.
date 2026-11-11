"""FastAPI boundary for the local React app; worker/browser stay on their own thread."""
import asyncio
from datetime import datetime
import json
from pathlib import Path
import sqlite3
from typing import Literal
from zoneinfo import ZoneInfo

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field
from starlette.middleware.trustedhost import TrustedHostMiddleware


class Action(BaseModel):
    model_config = ConfigDict(extra='forbid')
    action: Literal['login', 'start', 'disconnect', 'preferences', 'stop', 'answer', 'continue',
                    'click', 'text', 'key', 'scroll', 'captcha_submit', 'captcha_refresh', 'captcha_now', 'load_resumes', 'save_profile', 'select_profile', 'resume_queue', 'open_external']
    limit: int = Field(default=1000, ge=1, le=1000, strict=True)
    send: bool = False
    username: str = Field(default='', max_length=254)
    skip_questionnaires: bool = True
    skip_foreign_vacancies: bool = True
    gentle: bool = True
    text: str = Field(default='', max_length=32000)
    x: float = Field(default=0, ge=0, le=10000)
    y: float = Field(default=0, ge=0, le=10000)
    delta: int = Field(default=500, ge=-2000, le=2000)
    key: Literal['Tab', 'Enter', 'Backspace', 'ControlOrMeta+A'] = 'Tab'
    profile_id: str = Field(default='', max_length=100)
    profile_name: str = Field(default='', max_length=100)
    resume_id: str = Field(default='', max_length=100)
    search_mode: Literal['resume', 'keywords'] = 'resume'
    queries: list[str] = Field(default_factory=list, max_length=20)
    letter_mode: Literal['required', 'always', 'none'] = 'required'
    letter_text: str = Field(default='', max_length=10000)
    url: str = Field(default='', max_length=2048)
    queue_id: str = Field(default='', max_length=100)
    prompt_id: str | None = Field(default=None, max_length=100)


class Repository:
    def __init__(self, root):
        self.root = Path(root)
        self.candidate_stamp = None
        self.candidates = []

    def config(self):
        return json.loads((self.root / 'config.json').read_text(encoding='utf-8'))

    def connect(self):
        path = self.root / 'state.sqlite3'
        if not path.exists():
            return None
        db = sqlite3.connect(path.as_uri() + '?mode=ro', uri=True, timeout=2)
        db.row_factory = sqlite3.Row
        return db

    def history(self, status='', query='', page=1, size=20):
        db = self.connect()
        if db is None:
            return {'items': [], 'total': 0, 'page': page, 'size': size}
        try:
            where = 'resume_id=?'
            params = [self.config()['resume_id']]
            if status == 'attention':
                where += " AND status IN ('pending', 'uncertain', 'stopped')"
            elif status:
                where += ' AND status=?'
                params.append(status)
            if query:
                where += ' AND (title LIKE ? OR company LIKE ?)'
                params += [f'%{query}%', f'%{query}%']
            count = db.execute(f'SELECT COUNT(*) FROM applications WHERE {where}', params).fetchone()[0]
            rows = db.execute(f'SELECT * FROM applications WHERE {where} ORDER BY updated DESC LIMIT ? OFFSET ?',
                              params + [size, (page - 1) * size]).fetchall()
            return {'items': [dict(row) for row in rows], 'total': count, 'page': page, 'size': size}
        finally:
            db.close()

    def summary(self):
        db = self.connect()
        result = {'sent': 0, 'skipped': 0, 'already': 0, 'attention': 0, 'today_sent': 0}
        if db is None:
            return result
        today = datetime.now(ZoneInfo('Europe/Moscow')).date()
        try:
            rows = db.execute('SELECT status, updated FROM applications WHERE resume_id=?',
                              (self.config()['resume_id'],)).fetchall()
            for row in rows:
                key = {'sent': 'sent', 'review': 'skipped', 'already': 'already'}.get(row['status'], 'attention')
                result[key] += 1
                if row['status'] == 'sent':
                    try:
                        if datetime.fromisoformat(row['updated']).astimezone(ZoneInfo('Europe/Moscow')).date() == today:
                            result['today_sent'] += 1
                    except ValueError:
                        pass
            return result
        finally:
            db.close()

    def candidate_list(self, query='', page=1, size=20):
        path = self.root / 'candidates.json'
        if path.exists():
            stamp = (path.stat().st_mtime_ns, path.stat().st_size)
            if stamp != self.candidate_stamp:
                try:
                    self.candidates = json.loads(path.read_text(encoding='utf-8'))
                    self.candidate_stamp = stamp
                except (OSError, ValueError):
                    pass  # A write may be in progress; keep the last complete snapshot.
        items = [item for item in self.candidates if not query or query.lower() in
                 (item.get('title', '') + ' ' + (item.get('company') or '')).lower()]
        return {'items': items[(page - 1) * size:page * size], 'total': len(items), 'page': page, 'size': size}


def create_app(runtime=None, root=None):
    if runtime is None:
        import ui as runtime
    root = Path(root or runtime.ROOT)
    repo = Repository(root)
    app = FastAPI(title='Apply Local', docs_url=None, redoc_url=None, openapi_url=None)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=['127.0.0.1', 'localhost'])

    @app.middleware('http')
    async def local_boundary(request, call_next):
        if request.headers.get('origin') not in (None, f'{request.url.scheme}://{request.headers.get("host")}'):
            return JSONResponse({'error': 'Запрос разрешён только из локальной панели.'}, status_code=403)
        if request.url.path.startswith('/api/') and request.url.path not in ('/api/session', '/api/health'):
            if request.headers.get('x-token') != runtime.TOKEN:
                return JSONResponse({'error': 'Обновите страницу панели.'}, status_code=403)
        response = await call_next(request)
        response.headers['Cache-Control'] = 'no-store'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Referrer-Policy'] = 'no-referrer'
        response.headers['Content-Security-Policy'] = "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; font-src 'self'; frame-ancestors 'none'; base-uri 'self'"
        return response

    def snapshot():
        with runtime.mutex:
            value = dict(runtime.state)
            value['revision'] = runtime.state.revision
        import os
        value['desktop'] = os.environ.get('APPLY_DESKTOP') == '1'
        value['auth'] = runtime.hh_auth.status()
        value['preferences'] = runtime.preferences()
        config = repo.config()
        value['resume'] = {'title': config['resume_title'], 'url': 'https://hh.ru/resume/' + config['resume_id']}
        value['queries'] = config.get('queries', [])
        from profiles import Profiles
        value['profiles'] = Profiles(root).read()
        value['resumes'] = value.get('resumes', [])
        value['queue'] = None
        if (root / 'queue.sqlite3').exists():
            from queue_store import QueueStore
            store = QueueStore(root)
            try:
                value['queue'] = store.latest(config['resume_id'])
            finally:
                store.close()
        try:
            value['summary'] = repo.summary()
            value['history'] = repo.history()
            value['history_error'] = None
        except sqlite3.Error:
            value['summary'] = None
            value['history'] = {'items': [], 'total': 0, 'page': 1, 'size': 20}
            value['history_error'] = 'Не удалось прочитать журнал. Попробуйте обновить страницу.'
        value['candidate_count'] = repo.candidate_list()['total']
        return value

    @app.get('/api/health')
    def health():
        return {'app': 'apply-local', 'version': 2}

    @app.get('/api/session')
    def session():
        return {'token': runtime.TOKEN, 'state': snapshot()}

    @app.get('/api/state')
    def state():
        return snapshot()

    def wait_for_change(revision):
        with runtime.changed:
            if runtime.state.revision == revision:
                runtime.changed.wait(timeout=12)
            return runtime.state.revision

    @app.get('/api/events')
    async def events(request: Request):
        async def stream():
            revision = -1
            while not await request.is_disconnected():
                current = await asyncio.to_thread(wait_for_change, revision)
                if current == revision:
                    yield ': keepalive\n\n'
                    continue
                value = await asyncio.to_thread(snapshot)
                revision = value['revision']
                yield f'id: {revision}\nevent: state\ndata: {json.dumps(value, ensure_ascii=False)}\n\n'
        return StreamingResponse(stream(), media_type='text/event-stream',
                                 headers={'X-Accel-Buffering': 'no'})

    @app.post('/api/action')
    def action(body: Action):
        try:
            runtime.dispatch(body.model_dump())
        except (ValueError, OSError) as error:
            raise HTTPException(status_code=409, detail=str(error)) from None
        return {'ok': True}

    @app.get('/api/history')
    def history(status: str = '', q: str = '', page: int = 1):
        if page < 1 or len(q) > 200:
            raise HTTPException(422, 'Неверные параметры поиска')
        try:
            return repo.history(status=status, query=q, page=page)
        except sqlite3.Error:
            raise HTTPException(503, 'Журнал временно недоступен') from None

    @app.get('/api/candidates')
    def candidates(q: str = '', page: int = 1):
        if page < 1 or len(q) > 200:
            raise HTTPException(422, 'Неверные параметры поиска')
        return repo.candidate_list(query=q, page=page)

    from app_paths import RESOURCE_DIR
    dist = RESOURCE_DIR / 'frontend' / 'dist'
    if (dist / 'assets').exists():
        app.mount('/assets', StaticFiles(directory=dist / 'assets'), name='assets')

    @app.get('/favicon.svg')
    def favicon():
        if not (dist / 'favicon.svg').exists():
            raise HTTPException(404)
        return FileResponse(dist / 'favicon.svg')

    @app.get('/')
    def index():
        if not (dist / 'index.html').exists():
            raise HTTPException(503, 'Интерфейс ещё не собран. Запустите start.command.')
        return FileResponse(dist / 'index.html')

    return app
