"""Local adapter for hh-applicant-tool's SMS/email login and authenticated API.

The dependency owns the login protocol. No credentials are copied into source.
"""
from contextlib import contextmanager
from contextvars import ContextVar
import json
import logging
import os
from pathlib import Path
from types import SimpleNamespace

from app_paths import DATA_DIR
ROOT = DATA_DIR
AUTH_DIR = ROOT / 'auth-profile'
_client_scope = ContextVar('hh_client_scope', default=None)


def status():
    try:
        import secret_store
        token = secret_store.load(AUTH_DIR)
        identity = json.loads((AUTH_DIR / 'identity.json').read_text(encoding='utf-8'))
        return {'authenticated': bool(token.get('access_token')), 'name': identity.get('name', '')}
    except (OSError, ValueError, TypeError, RuntimeError):
        return {'authenticated': False, 'name': ''}



@contextmanager
def locked():
    AUTH_DIR.mkdir(mode=0o700, exist_ok=True)
    AUTH_DIR.chmod(0o700)
    from file_lock import acquire
    lock = acquire(AUTH_DIR / '.lock')
    try:
        yield
    finally:
        lock.release()



def private_json(path, value):
    temporary = path.with_suffix('.tmp')
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, 'w', encoding='utf-8') as stream:
        json.dump(value, stream, ensure_ascii=False)
    os.replace(temporary, path)
    path.chmod(0o600)


def make_tool(ui=None):
    try:
        import requests
        from hh_applicant_tool.tool import HHApplicantTool
    except ImportError:
        raise RuntimeError('Для входа установите зависимости: запустите start.command.') from None
    # The upstream debug logger can contain login payloads. Never enable it here.
    logging.getLogger('hh_applicant_tool').setLevel(logging.CRITICAL)

    class PanelTool(HHApplicantTool):
        def _save_token(self, token):
            import secret_store
            secret_store.save(AUTH_DIR, token)
            self.token_config.update(token=token)

        def _solve_captcha(self, image_data):
            if ui is None:
                raise RuntimeError('hh.ru требует капчу. Откройте панель управления.')
            observer = getattr(self, 'on_panel_captcha', None)
            if observer:
                observer()
            return ui.prompt('Введите текст с картинки hh.ru', image_data=image_data)

    class TimedSession(requests.Session):
        def request(self, *args, **kwargs):
            if ui is not None:
                ui.check_stop()
            kwargs.setdefault('timeout', (10, 40))
            return super().request(*args, **kwargs)

    tool = PanelTool(config_dir=AUTH_DIR, use_ai=False, captcha_manual=True,
                     captcha_handling=ui is not None)
    import secret_store
    token = secret_store.load(AUTH_DIR)
    if token:
        tool.token_config.update(token=token)
    # Preserve upstream headers/cookie loading while setting network timeouts.
    tool.session.__class__ = TimedSession
    tool.webview_session.__class__ = TimedSession
    tool.api_client.session.__class__ = TimedSession
    return tool


def authenticate(username, ui):
    username = username.strip()
    if not username or len(username) > 254:
        raise ValueError('Введите телефон или email аккаунта hh.ru.')
    with locked():
        from hh_applicant_tool.operations import authorize
        tool = make_tool(ui)
        original = getattr(authorize, 'input', None)
        authorize.input = lambda message: ui.prompt('Введите код из SMS или письма hh.ru')
        try:
            authorize.Operation().run(tool, SimpleNamespace(username=username, password=None))
            user = tool.get_me()
            if not user.get('is_applicant'):
                raise RuntimeError('Войдите в аккаунт соискателя.')
            name = ' '.join(filter(None, [user.get('first_name'), user.get('last_name')]))
            tool.save_cookies()
            private_json(AUTH_DIR / 'identity.json', {'name': name or 'Соискатель', 'id': user.get('id')})
            for path in AUTH_DIR.iterdir():
                if path.is_file():
                    path.chmod(0o600)
            return status()
        except BaseException:
            # Never expose an incomplete or unverified login as authenticated.
            import secret_store
            secret_store.clear(AUTH_DIR)
            (AUTH_DIR / 'identity.json').unlink(missing_ok=True)
            raise
        finally:
            if original is None:
                del authorize.input
            else:
                authorize.input = original


@contextmanager
def client_scope(ui=None):
    """Keep the upstream API client and session for the entire run."""
    marker = _client_scope.set({'ui': ui, 'tool': None})
    try:
        yield
    finally:
        slot = _client_scope.get()
        tool = slot.get('tool')
        if tool:
            for name in ('session', 'webview_session'):
                session = tool.__dict__.get(name)
                if session:
                    session.close()
            tool.api_client.session.close()
        _client_scope.reset(marker)


def current_tool(ui=None):
    slot = _client_scope.get()
    if slot is None:
        tool = make_tool(ui)
        if ui is not None:
            from captcha_gate import install
            install(tool.api_client, ui)
        return tool
    if slot['tool'] is None:
        slot['tool'] = make_tool(slot['ui'])
        if slot['ui'] is not None:
            from captcha_gate import install
            install(slot['tool'].api_client, slot['ui'])
    return slot['tool']


def get(path, params=None, ui=None):
    if not status()['authenticated']:
        raise RuntimeError('Сначала нажмите «Войти в hh.ru» вверху панели.')
    with locked():
        tool = current_tool(ui)
        try:
            return tool.api_client.get(path, params or {})
        except Exception as error:
            # Upstream exception strings may contain a full server payload.
            kind = type(error).__name__
            if kind in ('Forbidden', 'Unauthorized'):
                raise RuntimeError('API hh.ru отклонил авторизованный запрос. Войдите заново; если отказ повторяется, доступ ограничен сайтом.') from None
            raise RuntimeError(f'Запрос API hh.ru не выполнен ({kind}). Отклики не отправлялись.') from None


def disconnect():
    with locked():
        import secret_store
        secret_store.clear(AUTH_DIR)
        for name in ('token.json', 'identity.json', 'cookies.txt'):
            (AUTH_DIR / name).unlink(missing_ok=True)


def browser_cookies():
    """Use the same login in Chromium; do not export cookies to the UI."""
    from http.cookiejar import MozillaCookieJar
    import time
    path = AUTH_DIR / 'cookies.txt'
    if not path.exists():
        return []
    jar = MozillaCookieJar(str(path))
    jar.load(ignore_discard=True, ignore_expires=False)
    result = []
    for cookie in jar:
        if cookie.domain.lstrip('.') != 'hh.ru' and not cookie.domain.endswith('.hh.ru'):
            continue
        value = {'name': cookie.name, 'value': cookie.value, 'domain': cookie.domain,
                 'path': cookie.path or '/', 'secure': cookie.secure,
                 'httpOnly': cookie.has_nonstandard_attr('HTTPOnly') or cookie.has_nonstandard_attr('HttpOnly')}
        if cookie.expires and cookie.expires > time.time():
            value['expires'] = cookie.expires
        result.append(value)
    return result
