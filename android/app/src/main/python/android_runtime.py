"""Android host for the shared queue/API engine. No background WebView or local server."""
import base64
import json
import os
from pathlib import Path
import re
import threading
import time
from urllib.parse import parse_qs, urljoin, urlsplit

_host = None
_initialized = False
_stop_reason = ''


def initialize(host, directory):
    global _host, _initialized
    _host = host
    if _initialized:
        return True
    os.environ['APPLY_ANDROID'] = '1'
    os.environ['APPLY_DATA_DIR'] = directory
    from app_paths import initialize as init_paths
    init_paths()
    import ui
    # Fail visibly at startup if packaging omitted an API dependency. No HH requests.
    tool = ui.hh_auth.make_tool()
    tool.session.close()
    tool.webview_session.close()
    tool.api_client.session.close()
    from queue_store import QueueStore
    from hh_apply import Journal
    from file_lock import acquire
    lock = acquire(ui.ROOT / '.run.lock')
    try:
        journal = Journal(ui.ROOT / 'state.sqlite3')
        store = QueueStore(ui.ROOT)
        try:
            store.recover(journal)
        finally:
            journal.db.close()
            store.close()
    finally:
        lock.release()
    _initialized = True
    return True


def secrets_load():
    raw = _host.readSecret()
    return json.loads(str(raw)) if raw else {}


def secrets_save(token):
    _host.writeSecret(json.dumps(token))


def announce(title, body):
    _host.notice(title, body)


def open_external(url):
    _host.openExternal(url)


def authorize(username, panel, make_tool):
    """OTP flow based on hh-applicant-tool 2.5.4, with Android RSA-OAEP.

    See THIRD_PARTY_NOTICES.md and the bundled upstream distribution license.
    The upstream package is unmodified. CLI/password/image extras aren't loaded.
    """
    import hh_auth
    tool = make_tool(panel)
    try:
        api, session = tool.api_client, tool.session
        is_email = '@' in username
        if not is_email:
            username = re.sub(r'\D', '', username)
            if len(username) == 11 and username.startswith('8'):
                username = '7' + username[1:]
        response = session.get(api.oauth_client.authorize_url(
            force_login='true', role='applicant', force_role='true', skip_choose_account='true'))
        response.raise_for_status()
        redirect = response.url
        if urlsplit(redirect).scheme != 'https' or not hh_url(redirect):
            raise RuntimeError('Неподдерживаемый адрес авторизации.')
        initial = tool.parse_initial_state(response)
        if initial['xsrfToken'] != tool.xsrf_token:
            raise RuntimeError('Не удалось подтвердить сессию входа.')
        key = initial['loginTrustFlagsSecret']
        backurl = parse_qs(urlsplit(redirect).query)['backurl'][0]

        def flags(payload=None):
            value = dict(payload or {}, ts=int(time.time() * 1000))
            return str(_host.encryptLogin(key, json.dumps(value, separators=(',', ':'))))

        def xhr(path, data):
            panel.check_stop()
            return tool.xhr_request('POST', urljoin(redirect, path), data=data,
                referer_url=redirect, additional_headers={'X-Hhtmfrom': '', 'X-Hhtmsource': 'account_login'})

        # Preserve the upstream delay; it remains cancellable on a phone.
        for _ in range(20):
            panel.check_stop()
            time.sleep(.25)
        result = xhr('/account/otp_generate', {'login': username, 'otpType': 'email' if is_email else 'phone',
            'operationType': 'applicant_otp_auth', 'authScenario': 'APPLICANT_AUTH', 'formatPhone': 'true',
            'isSignupPage': 'false', 'loginTrustFlags': flags({'emailOrPhone': {'paste': False, 'suggest': True}}),
            'captchaText': ''})
        if not result.get('success'):
            raise RuntimeError('Не удалось запросить код входа.')
        code = panel.prompt('Введите код из SMS или письма hh.ru')
        result = xhr('/account/login/by_code', {'username': username, 'code': code, 'backurl': redirect,
            'operationType': 'applicant_otp_auth', 'isApplicantSignup': 'false', 'remember': 'true',
            'loginTrustFlags': flags(), 'authScenario': 'APPLICANT_AUTH'})
        if not result.get('success') or not result.get('verification', {}).get('success'):
            raise RuntimeError('Код входа не принят.')
        target = urljoin(redirect, backurl)
        if not hh_url(target):
            raise RuntimeError('Неподдерживаемый адрес подтверждения входа.')
        result = session.get(target, headers={'Referer': redirect}, allow_redirects=False)
        location = urlsplit(result.headers.get('location', ''))
        if result.status_code != 302 or location.scheme != 'hhandroid' or location.netloc != 'oauthresponse':
            raise RuntimeError('Вход не подтверждён hh.ru.')
        api.handle_access_token(api.oauth_client.authenticate(parse_qs(location.query)['code'][0]))
        user = tool.get_me()
        if not user.get('is_applicant'):
            raise RuntimeError('Войдите в аккаунт соискателя.')
        name = ' '.join(filter(None, [user.get('first_name'), user.get('last_name')]))
        tool.save_cookies()
        hh_auth.private_json(hh_auth.AUTH_DIR / 'identity.json', {'name': name or 'Соискатель', 'id': user.get('id')})
        return hh_auth.status()
    except BaseException:
        secrets_save({})
        (hh_auth.AUTH_DIR / 'identity.json').unlink(missing_ok=True)
        raise
    finally:
        tool.session.close()
        tool.webview_session.close()
        tool.api_client.session.close()


def hh_url(url):
    value = urlsplit(url)
    host = value.hostname or ''
    return value.scheme == 'https' and (host == 'hh.ru' or host.endswith('.hh.ru'))


def snapshot():
    import ui
    from repository import Repository
    from profiles import Profiles
    from queue_store import QueueStore
    repo = Repository(ui.ROOT)
    with ui.mutex:
        value = dict(ui.state, revision=ui.state.revision)
    if _stop_reason and not value['running'] and value['phase'] == 'stopped':
        value['message'] = _stop_reason
    config = repo.config()
    value.update(desktop=True, android=True, auth=ui.hh_auth.status(), preferences=ui.preferences(),
        resume={'title': config['resume_title'], 'url': 'https://hh.ru/resume/' + config['resume_id']},
        queries=config.get('queries', []), profiles=Profiles(ui.ROOT).read(),
        summary=repo.summary(), history=repo.history(), history_error=None,
        candidate_count=repo.candidate_list()['total'], queue=None)
    store = QueueStore(ui.ROOT)
    try:
        value['queue'] = store.latest(config['resume_id'])
    finally:
        store.close()
    return value


def request(path, body=''):
    global _stop_reason
    import ui
    from repository import Repository
    from urllib.parse import urlsplit, parse_qs
    try:
        url = urlsplit(path)
        params = parse_qs(url.query)
        if url.path in ('/api/session', '/api/state'):
            result = {'token': '', 'state': snapshot()} if url.path.endswith('session') else snapshot()
        elif url.path == '/api/action':
            data = json.loads(body)
            action = data.get('action')
            if action == 'open_battery_settings':
                _host.openBatterySettings()
                return json.dumps({'ok': True, 'value': {'ok': True}})
            if action not in {'login', 'start', 'disconnect', 'preferences', 'stop', 'answer', 'captcha_now',
                              'load_resumes', 'save_profile', 'select_profile', 'resume_queue', 'open_external'}:
                raise ValueError('Действие недоступно в Android.')
            if len(body) > 64000:
                raise ValueError('Слишком большой запрос.')
            if action in {'start', 'resume_queue', 'login', 'load_resumes'}:
                # Must succeed before dispatch: Android rejects new background starts.
                _host.beginWork()
            ui.dispatch(data)
            if action in {'start', 'resume_queue', 'login', 'load_resumes'}:
                _stop_reason = ''
            result = {'ok': True}
        elif url.path in ('/api/history', '/api/candidates'):
            repo = Repository(ui.ROOT)
            page = int(params.get('page', ['1'])[0])
            query = params.get('q', [''])[0]
            if page < 1 or len(query) > 200:
                raise ValueError('Неверные параметры поиска.')
            result = repo.history(params.get('status', [''])[0], query, page) if url.path.endswith('history') else repo.candidate_list(query, page)
        else:
            raise ValueError('Неизвестный запрос.')
        return json.dumps({'ok': True, 'value': result}, ensure_ascii=False)
    except Exception:
        return json.dumps({'ok': False, 'error': 'Не удалось выполнить действие. Проверьте настройки и состояние запуска.'}, ensure_ascii=False)


def status():
    import ui
    with ui.mutex:
        return json.dumps({'running': ui.state['running'], 'waiting': ui.state['waiting'],
            'phase': ui.state['phase'], 'sent': ui.state.get('run', {}).get('sent', 0),
            'limit': ui.state.get('run', {}).get('limit', 0), 'revision': ui.state.revision})


def stop(reason=''):
    global _stop_reason
    import ui
    if reason:
        _stop_reason = reason
    ui.stop_requested.set()
    ui.commands.put({'action': 'stop'})
