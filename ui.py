"""Loopback-only control panel. Browser actions run on the Playwright owner thread."""
import base64
import json
import queue
import secrets
import threading
import webbrowser
import time
import sys
import socket
import uuid
from pathlib import Path
import hh_auth

from app_paths import DATA_DIR
ROOT = DATA_DIR
TOKEN = secrets.token_urlsafe(32)
commands = queue.Queue()
mutex = threading.RLock()
changed = threading.Condition(mutex)


class LiveState(dict):
    revision = 0

    def __setitem__(self, key, value):
        with changed:
            if self.get(key) == value:
                return
            super().__setitem__(key, value)
            self.revision += 1
            changed.notify_all()

    def update(self, *args, **kwargs):
        with changed:
            for key, value in dict(*args, **kwargs).items():
                self[key] = value


state = LiveState(running=False, waiting=False, message='Готов к запуску', logs=[], image='',
                  prompt_kind='browser', manual_captcha=False, prompt_id=None, phase='idle',
                  operation=None, run={})
stop_requested = threading.Event()
shutdown_requested = threading.Event()


def preferences():
    defaults = {'limit': 1000, 'skip_questionnaires': True, 'skip_foreign_vacancies': True, 'gentle': True}
    try:
        saved = json.loads((ROOT / 'ui-settings.json').read_text(encoding='utf-8'))
        if type(saved.get('limit')) is int and 1 <= saved['limit'] <= 1000:
            defaults['limit'] = saved['limit']
        for key in ('skip_questionnaires', 'skip_foreign_vacancies', 'gentle'):
            if type(saved.get(key)) is bool:
                defaults[key] = saved[key]
    except (OSError, ValueError, AttributeError):
        pass
    return defaults


def progress(**values):
    with mutex:
        message = values.pop('message', None)
        if message is not None:
            state['message'] = message
        phase = values.pop('phase', None)
        if phase:
            state['phase'] = phase
        state['run'] = dict(state.get('run', {}), **values)


def entry(vacancy, status, note):
    with mutex:
        run = dict(state.get('run', {}))
        counter = {'sent': 'sent', 'review': 'skipped', 'already': 'already'}.get(status, 'attention')
        run[counter] = run.get(counter, 0) + 1
        run['processed'] = run.get('processed', 0) + 1
        state['run'] = run


def reset_run(limit, operation):
    stop_requested.clear()
    while not commands.empty():
        commands.get_nowait()
    state.update(running=True, waiting=False, logs=[], phase='searching' if operation != 'login' else 'login',
                 operation=operation, message='Поиск вакансий…' if operation != 'login' else 'Подключаюсь к hh.ru…',
                 run={'id': uuid.uuid4().hex, 'limit': limit, 'total': 0, 'sent': 0, 'skipped': 0,
                      'already': 0, 'attention': 0, 'processed': 0, 'current': None,
                      'pause_until': None, 'started_at': time.time(), 'finished_at': None})


def announce(title, body):
    import os
    if os.environ.get('APPLY_DESKTOP') == '1':
        print('APPLY_NOTICE ' + json.dumps({'title': title, 'body': body}, ensure_ascii=False), flush=True)


def wait_captcha(seconds, attempt):
    previous = state.get('phase', 'sending')
    deadline = time.monotonic() + seconds
    progress(phase='captcha_wait', captcha_attempt=attempt, pause_until=time.time() + seconds,
             message=f'Капча: пауза {attempt} из 2. После двух проверок потребуется ручной ввод.')
    try:
        while time.monotonic() < deadline:
            if stop_requested.is_set():
                raise KeyboardInterrupt
            try:
                command = commands.get(timeout=min(.25, max(.01, deadline - time.monotonic())))
            except queue.Empty:
                continue
            if command.get('action') == 'stop':
                raise KeyboardInterrupt
            if command.get('action') == 'captcha_now':
                return False
        return True
    finally:
        progress(phase=previous, pause_until=None)


def dispatch(data):
    action = data.get('action')
    with mutex:
        if action in ('login', 'start', 'disconnect', 'preferences', 'load_resumes', 'save_profile', 'select_profile', 'resume_queue') and state['running']:
            raise ValueError('Сначала остановите текущий запуск.')
        if action == 'open_external':
            from urllib.parse import urlparse
            url = data.get('url', '')
            parsed = urlparse(url)
            host = parsed.hostname or ''
            if parsed.scheme != 'https' or not (host == 'github.com' or host == 'hh.ru' or host.endswith('.hh.ru')):
                raise ValueError('Неподдерживаемая внешняя ссылка.')
            webbrowser.open(url)
        elif action == 'load_resumes':
            if not hh_auth.status()['authenticated']:
                raise ValueError('Сначала войдите в hh.ru.')
            reset_run(0, 'resumes')
            threading.Thread(target=resumes_worker, daemon=True).start()
        elif action in ('save_profile', 'select_profile'):
            from profiles import Profiles
            profiles = Profiles(ROOT)
            if action == 'save_profile':
                profiles.upsert(data, state.get('resumes', []))
            else:
                profiles.select(data.get('profile_id'))
            state.update(message='Профиль сохранён', profile_revision=time.time_ns())
        elif action == 'resume_queue':
            if not hh_auth.status()['authenticated']:
                raise ValueError('Сначала войдите в hh.ru.')
            from queue_store import QueueStore
            store = QueueStore(ROOT)
            try:
                saved = store.get(data.get('queue_id', ''))
                current = json.loads((ROOT / 'config.json').read_text(encoding='utf-8'))
                if saved['resume_id'] != current['resume_id']:
                    raise ValueError('Выберите профиль с резюме этой очереди.')
                if saved['remaining'] == 0 or saved['sent'] >= saved['max_count']:
                    raise ValueError('В этой очереди больше нет доступных откликов.')
                settings = saved['config']
                limit = saved['max_count']
            finally:
                store.close()
            reset_run(limit, 'send')
            threading.Thread(target=worker, args=(True, limit, dict(settings, _queue_run_id=data['queue_id'])), daemon=True).start()
        elif action == 'login':
            username = str(data.get('username', '')).strip()
            if not username or len(username) > 254:
                raise ValueError('Введите телефон или email аккаунта hh.ru.')
            reset_run(0, 'login')
            threading.Thread(target=login_worker, args=(username,), daemon=True).start()
        elif action in ('start', 'preferences'):
            limit = data.get('limit', 1000)
            if type(limit) is not int or not 1 <= limit <= 1000:
                raise ValueError('Максимум откликов: целое число от 1 до 1000.')
            settings = {'limit': limit, **{key: data.get(key, True) is True for key in
                        ('skip_questionnaires', 'skip_foreign_vacancies', 'gentle')}}
            if action == 'start' and not hh_auth.status()['authenticated']:
                raise ValueError('Сначала войдите в hh.ru.')
            hh_auth.private_json(ROOT / 'ui-settings.json', settings)
            state['preferences_version'] = time.time_ns()
            if action == 'preferences':
                state['message'] = 'Настройки сохранены'
                return
            reset_run(limit, 'send' if data.get('send') is True else 'preview')
            options = {key: value for key, value in settings.items() if key != 'limit'}
            threading.Thread(target=worker, args=(data.get('send') is True, limit, options), daemon=True).start()
        elif action == 'disconnect':
            hh_auth.disconnect()
            state['message'] = 'Аккаунт отключён. Вход в браузере hh.ru может сохраняться.'
        elif action == 'captcha_now':
            if state.get('phase') != 'captcha_wait':
                raise ValueError('Сейчас нет ожидания капчи.')
            commands.put({'action': 'captcha_now'})
        elif action == 'stop':
            if state['running']:
                stop_requested.set()
                state.update(phase='stopping', message='Останавливаем после текущего запроса…')
                commands.put({'action': 'stop'})
        elif action in ('answer', 'continue', 'click', 'text', 'key', 'scroll', 'captcha_submit', 'captcha_refresh'):
            if not state['waiting']:
                raise ValueError('Сейчас ввод не требуется.')
            if data.get('prompt_id') != state.get('prompt_id'):
                raise ValueError('Эта форма уже обновилась. Используйте текущую картинку или вопрос.')
            commands.put(data)
        else:
            raise ValueError('Неизвестное действие.')



def log(message):
    with mutex:
        state['logs'] = (state['logs'] + [str(message)])[-300:]


def manual(page, message, captcha_mode=False):
    import captcha_ui
    refreshed_error = None
    prompt_id = secrets.token_urlsafe(12)
    announce('Apply ждёт вашего ответа', message)
    with mutex:
        state.update(waiting=True, message=message, prompt_kind='browser', manual_captcha=captcha_mode,
                     prompt_id=prompt_id)
    try:
        while True:
            if captcha_mode:
                if not captcha_ui.is_open(page):
                    return
                error = captcha_ui.error_text(page)
                if error and error != refreshed_error:
                    refreshed_error = error
                    updated = captcha_ui.refresh(page)
                    with mutex:
                        state['message'] = ('Ответ не принят. Загружается новая картинка — введите её текст.'
                                            if updated else 'Ответ не принят. Нажмите стрелку обновления под картинкой на странице.')
                    page.wait_for_timeout(350)
                elif not error:
                    refreshed_error = None
            frame = base64.b64encode(page.screenshot(type='jpeg', quality=65)).decode()
            with mutex:
                state['image'] = frame
            try:
                action = commands.get(timeout=.4)
            except queue.Empty:
                continue
            if action.get('prompt_id') is not None and action['prompt_id'] != prompt_id and action.get('action') != 'stop':
                continue
            kind = action.get('action')
            if kind == 'stop':
                raise KeyboardInterrupt
            if kind == 'continue':
                if captcha_mode and captcha_ui.is_open(page):
                    with mutex:
                        state['message'] = 'Сначала отправьте правильный ответ на капчу.'
                    continue
                return
            if kind == 'captcha_refresh' and captcha_mode:
                updated = captcha_ui.refresh(page)
                with mutex:
                    state['message'] = ('Загружается новая картинка капчи.' if updated else
                                        'Нажмите стрелку обновления под картинкой на странице.')
            elif kind == 'captcha_submit' and captcha_mode:
                text = str(action.get('text', '')).strip()
                if text:
                    refreshed_error = None
                    captcha_ui.submit(page, text)
                    with mutex:
                        state['message'] = 'Проверяю ответ на капчу…'
            elif kind == 'click':
                page.mouse.click(float(action['x']), float(action['y']))
            elif kind == 'text':
                page.keyboard.insert_text(str(action.get('text', '')))
            elif kind == 'key' and action.get('key') in ('Tab', 'Enter', 'Backspace', 'ControlOrMeta+A'):
                page.keyboard.press(action['key'])
            elif kind == 'scroll':
                page.mouse.wheel(0, int(action.get('delta', 500)))
            page.wait_for_timeout(200)
    finally:
        with mutex:
            state.update(waiting=False, image='', manual_captcha=False, prompt_id=None)


def prompt(message, image_data=None):
    """One-time code / CAPTCHA input, kept only in memory and never logged."""
    prompt_id = secrets.token_urlsafe(12)
    announce('Apply ждёт вашего ответа', message)
    with mutex:
        state.update(waiting=True, message=message, prompt_kind='auth', prompt_id=prompt_id,
                     image=base64.b64encode(image_data).decode() if image_data else '')
    try:
        while True:
            try:
                action = commands.get(timeout=.4)
            except queue.Empty:
                continue
            if action.get('action') == 'stop':
                raise KeyboardInterrupt
            if action.get('action') == 'answer':
                if action.get('prompt_id') is not None and action['prompt_id'] != prompt_id:
                    continue
                value = str(action.get('text', '')).strip()
                if value:
                    return value
    finally:
        with mutex:
            state.update(waiting=False, image='', prompt_kind='browser', prompt_id=None)


def resumes_worker():
    try:
        with hh_auth.client_scope(sys.modules[__name__]):
            payload = hh_auth.get('/resumes/mine', ui=sys.modules[__name__])
        values = [{'id': str(r['id']), 'title': r.get('title', 'Без названия')} for r in payload.get('items', [])]
        state.update(resumes=values, message='Список резюме обновлён', phase='idle')
    except KeyboardInterrupt:
        state.update(message='Загрузка резюме отменена', phase='stopped')
    except Exception:
        state.update(message='Не удалось загрузить резюме. Проверьте вход в hh.ru.', phase='error')
    finally:
        state.update(running=False, operation=None)
        stop_requested.clear()


def login_worker(username):
    phase = 'idle'
    try:
        hh_auth.authenticate(username, __import__(__name__))
        log('Вход в hh.ru подтверждён. Поиск использует авторизацию аккаунта.')
        message = 'Вы вошли в hh.ru'
    except KeyboardInterrupt:
        phase = 'stopped'
        message = 'Вход отменён'
    except Exception as error:
        # Do not forward raw upstream errors: they can contain login payloads.
        phase = 'error'
        message = 'Не удалось войти. Проверьте телефон/email и код, затем попробуйте снова.'
        log(f'Вход не выполнен ({type(error).__name__}).')
    finally:
        with mutex:
            state.update(running=False, waiting=False, message=message, phase=phase, operation=None)
        stop_requested.clear()


def check_stop():
    if stop_requested.is_set():
        raise KeyboardInterrupt
    try:
        action = commands.get_nowait()
    except queue.Empty:
        return
    if action.get('action') == 'stop':
        raise KeyboardInterrupt


def worker(send, limit, options):
    import hh_apply
    phase = 'completed'
    message = 'Запуск завершён'
    try:
        hh_apply.main(['--send', '--limit', str(limit)] if send else [], ui=sys.modules[__name__], options=options)
        with mutex:
            if state['phase'] in ('error', 'stopped'):
                phase = state['phase']
                message = state['message']
    except KeyboardInterrupt:
        phase, message = 'stopped', 'Остановлено вами. Незавершённые отклики не повторятся автоматически.'
        log(message)
    except Exception as error:
        phase, message = 'error', str(error)
        log(f'Ошибка: {error}')
    finally:
        with mutex:
            state.update(running=False, waiting=False, message=message, phase=phase)
            progress(current=None, pause_until=None, finished_at=time.time())
        stop_requested.clear()


def main(port=55015, open_browser=True):
    import uvicorn
    from app_paths import initialize
    initialize()
    if (ROOT / 'queue.sqlite3').exists():
        from file_lock import acquire
        from queue_store import QueueStore
        from hh_apply import Journal
        try:
            recovery_lock = acquire(ROOT / '.run.lock')
        except RuntimeError:
            recovery_lock = None
        if recovery_lock:
            journal = Journal(ROOT / 'state.sqlite3')
            store = QueueStore(ROOT)
            try:
                store.recover(journal)
            finally:
                store.close()
                journal.db.close()
                recovery_lock.release()
    from server import create_app
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.bind(('127.0.0.1', port))
    except OSError:
        sock.close()
        raise SystemExit(f'Порт {port} уже занят. Закройте прежнее окно запуска или выберите другой порт.')
    actual_port = sock.getsockname()[1]
    url = f'http://127.0.0.1:{actual_port}'
    import os
    if os.environ.get('APPLY_DESKTOP') != '1':
        print('Панель управления: ' + url, flush=True)
    app = create_app(runtime=sys.modules[__name__])
    if open_browser:
        opener = threading.Timer(.8, webbrowser.open, args=(url,))
        opener.daemon = True
        opener.start()
    try:
        server = uvicorn.Server(uvicorn.Config(app, host='127.0.0.1', port=actual_port, log_level='warning'))
        def ready_announcer():
            while not server.started:
                time.sleep(.05)
            if os.environ.get('APPLY_DESKTOP') == '1':
                print('APPLY_READY ' + json.dumps({'port': actual_port}), flush=True)
        threading.Thread(target=ready_announcer, daemon=True).start()
        def shutdown_watcher():
            shutdown_requested.wait()
            stop_requested.set()
            commands.put({'action': 'stop'})
            deadline = time.monotonic() + 40
            while state['running'] and time.monotonic() < deadline:
                time.sleep(.1)
            server.should_exit = True
        threading.Thread(target=shutdown_watcher, daemon=True).start()
        server.run(sockets=[sock])
    finally:
        sock.close()


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description='Apply — локальная панель откликов')
    parser.add_argument('--port', type=int, default=55015)
    parser.add_argument('--no-open', action='store_true')
    args = parser.parse_args()
    main(port=args.port, open_browser=not args.no_open)
