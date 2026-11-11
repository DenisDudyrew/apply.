"""End-to-end UI checks on an isolated fake account. No HH requests or real applications."""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import json
import socket
import tempfile
import threading
import time
from unittest.mock import patch, Mock
import uvicorn
from playwright.sync_api import sync_playwright, expect
import hh_apply
import hh_auth
import ui
from server import create_app

ROOT = Path(__file__).resolve().parents[1]


def run():
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        (root / 'frontend').symlink_to(ROOT / 'frontend', target_is_directory=True)
        config = {'resume_id': 'test-resume', 'resume_title': 'Системный аналитик', 'queries': ['системный аналитик', 'бизнес аналитик']}
        (root / 'config.json').write_text(json.dumps(config))
        (root / 'candidates.json').write_text('[]')
        journal = hh_apply.Journal(root / 'state.sqlite3')
        journal.put('test-resume', {'id': 'old', 'name': 'Неизвестная доставка', 'alternate_url': 'https://hh.ru/vacancy/old'}, 'uncertain', 'Проверьте вручную на hh.ru')
        journal.db.close()
        authenticated = {'value': False}
        images = []
        manual_page = Mock()

        def auth(username, panel):
            assert username == 'test@example.test'
            assert panel.prompt('Введите код из письма hh.ru') == '246810'
            authenticated['value'] = True

        def fake_main(argv, ui, options):
            vacancies = [{'id': str(i), 'title': f'Системный аналитик {i}', 'company': 'Тестовая компания', 'url': f'https://hh.ru/vacancy/{i}'} for i in range(12)]
            (root / 'candidates.json').write_text(json.dumps(vacancies))
            ui.progress(total=12, phase='verifying')
            ui.log('Тестовый поиск завершён')
            if '--send' not in argv:
                return
            assert argv[-1] == '37'
            assert options['skip_questionnaires'] is False
            vacancy = {'id': 'new', 'name': 'Системный аналитик', 'alternate_url': 'https://hh.ru/vacancy/new', 'employer': {'name': 'Тестовая компания'}}
            journal = hh_apply.Journal(root / 'state.sqlite3')
            try:
                ui.progress(phase='sending', current={'title': vacancy['name'], 'company': 'Тестовая компания', 'url': vacancy['alternate_url']})
                journal.put('test-resume', vacancy, 'sent', 'Подтверждено')
                ui.entry(vacancy, 'sent', 'Подтверждено')
                ui.progress(phase='pausing', pause_until=time.time() + 3)
                deadline = time.monotonic() + 3
                while time.monotonic() < deadline:
                    ui.check_stop()
                    time.sleep(.05)
                assert ui.prompt('Введите текст с картинки', image_data=images[0]) == 'wrong'
                assert ui.prompt('Ответ не принят. Введите текст новой картинки', image_data=images[1]) == 'correct'
                ui.progress(phase='sending', pause_until=None)
                manual_page.screenshot.return_value = images[0]
                ui.manual(manual_page, 'Заполните тестовую анкету в панели')
                while True:
                    ui.check_stop()
                    time.sleep(.05)
            finally:
                journal.db.close()

        with patch.object(ui, 'ROOT', root), patch.object(hh_auth, 'status', side_effect=lambda: {'authenticated': authenticated['value'], 'name': 'Тестовый аккаунт' if authenticated['value'] else ''}), patch.object(hh_auth, 'authenticate', side_effect=auth), patch.object(hh_auth, 'get', return_value={'items': [{'id': 'test-resume', 'title': 'Системный аналитик'}, {'id': 'dev-resume', 'title': 'Python Developer'}]}), patch.object(hh_auth, 'disconnect', side_effect=lambda: authenticated.update(value=False)), patch.object(hh_apply, 'main', side_effect=fake_main):
            ui.state.update(running=False, waiting=False, phase='idle', run={}, image='', logs=[])
            ui.stop_requested.clear()
            sock = socket.socket()
            sock.bind(('127.0.0.1', 0))
            port = sock.getsockname()[1]
            server = uvicorn.Server(uvicorn.Config(create_app(runtime=ui, root=root), log_level='error'))
            thread = threading.Thread(target=server.run, kwargs={'sockets': [sock]}, daemon=True)
            thread.start()
            for _ in range(100):
                if server.started:
                    break
                time.sleep(.05)
            try:
                with sync_playwright() as p:
                    browser = p.chromium.launch(headless=True)
                    page = browser.new_page(viewport={'width': 1440, 'height': 1100})
                    page.set_default_timeout(12000)
                    errors, requests = [], []
                    page.on('pageerror', lambda e: errors.append(str(e)))
                    page.on('request', lambda r: requests.append(r.url))
                    # Two visually distinct local images stand in for server CAPTCHA pictures.
                    for color in ('#a2cb55', '#b28ee1'):
                        page.set_content(f'<body style="background:{color};margin:0"><p>Тестовая картинка</p></body>')
                        images.append(page.screenshot(type='png'))
                    page.goto(f'http://127.0.0.1:{port}')
                    expect(page.get_by_text('На связи', exact=True)).to_be_visible()
                    expect(page.get_by_label('Максимум откликов', exact=True)).to_have_value('1000')
                    page.get_by_role('button', name='Подключить hh.ru', exact=True).click()
                    page.get_by_label('Телефон или email', exact=True).fill('test@example.test')
                    page.get_by_role('button', name='Получить код', exact=True).click()
                    page.get_by_label('Код подтверждения', exact=True).fill('246810')
                    page.get_by_role('button', name='Подтвердить', exact=True).click()
                    expect(page.get_by_role('button', name='Запустить отклики', exact=True)).to_be_enabled()
                    page.get_by_label('Максимум откликов', exact=True).fill('37')
                    page.get_by_role('switch', name='Без анкет', exact=True).click()
                    page.get_by_role('button', name='Только найти', exact=True).click()
                    expect(page.get_by_role('button', name='Запустить отклики', exact=True)).to_be_enabled()
                    page.get_by_role('button', name='Вакансии', exact=True).click()
                    expect(page.get_by_role('link', name='Посмотреть вакансию')).to_have_count(12)
                    page.get_by_role('button', name='Обзор', exact=True).click()
                    page.get_by_role('button', name='Запустить отклики', exact=True).click()
                    expect(page.get_by_text('Следующий отклик через', exact=False)).to_be_visible()
                    page.get_by_label('Текст капчи', exact=True).fill('wrong')
                    first_image = page.get_by_alt_text('Картинка капчи hh.ru').get_attribute('src')
                    page.get_by_role('button', name='Подтвердить', exact=True).click()
                    expect(page.get_by_text('Ответ не принят. Введите текст новой картинки', exact=True)).to_be_visible()
                    expect(page.get_by_label('Текст капчи', exact=True)).to_have_value('')
                    assert page.get_by_alt_text('Картинка капчи hh.ru').get_attribute('src') != first_image
                    page.get_by_label('Текст капчи', exact=True).fill('correct')
                    page.get_by_role('button', name='Подтвердить', exact=True).click()
                    image = page.get_by_alt_text('Текущая страница hh.ru — нажимайте на поля и кнопки')
                    expect(image).to_be_visible()
                    image.click(position={'x': 30, 'y': 30})
                    page.get_by_label('Текст для выбранного поля', exact=True).fill('Ответ пользователя')
                    page.get_by_role('button', name='Вставить', exact=True).click()
                    page.get_by_role('button', name='Ниже', exact=True).click()
                    page.get_by_role('button', name='Готово, продолжить', exact=True).click()
                    manual_page.keyboard.insert_text.assert_called_once_with('Ответ пользователя')
                    manual_page.mouse.click.assert_called_once()
                    manual_page.mouse.wheel.assert_called_once_with(0, 550)
                    page.get_by_role('button', name='Остановить запуск', exact=True).click()
                    expect(page.get_by_role('button', name='Запустить отклики', exact=True)).to_be_enabled()
                    expect(page.get_by_text('Запуск остановлен', exact=True).first).to_be_visible()
                    page.get_by_role('button', name='История откликов', exact=True).click()
                    page.get_by_label('Фильтр статуса', exact=True).select_option('attention')
                    expect(page.get_by_role('link', name='Неизвестная доставка')).to_be_visible()
                    page.get_by_role('button', name='Подробнее: Неизвестная доставка').click()
                    expect(page.get_by_text('Проверьте вручную на hh.ru', exact=True)).to_be_visible()
                    page.get_by_role('button', name='Настройки', exact=True).click()
                    page.get_by_label('Максимум откликов', exact=True).fill('89')
                    page.get_by_role('button', name='Сохранить настройки', exact=True).click()
                    expect(page.get_by_role('status').filter(has_text='Настройки сохранены')).to_be_visible()
                    assert json.loads((root / 'ui-settings.json').read_text())['limit'] == 89
                    page.get_by_role('button', name='Новый профиль', exact=True).click()
                    page.get_by_role('button', name='Загрузить резюме', exact=True).click()
                    expect(page.get_by_label('Резюме hh.ru', exact=True)).to_be_enabled()
                    page.get_by_label('Резюме hh.ru', exact=True).select_option('dev-resume')
                    page.get_by_label('Название профиля', exact=True).fill('Разработка')
                    page.get_by_label('Сопроводительное письмо', exact=True).select_option('always')
                    page.get_by_label('Шаблон письма', exact=True).fill('Для {company}: {vacancy} / {resume}')
                    page.get_by_role('button', name='Сохранить профиль и письмо', exact=True).click()
                    expect(page.get_by_role('status').filter(has_text='Профиль и письмо сохранены')).to_be_visible()
                    assert json.loads((root / 'config.json').read_text())['resume_id'] == 'dev-resume'
                    assert json.loads((root / 'config.json').read_text())['letter_mode'] == 'always'
                    page.get_by_role('button', name='Обзор', exact=True).click()
                    expect(page.get_by_label('Активный профиль', exact=True)).to_have_value(json.loads((root / 'profiles.json').read_text())['selected'])
                    ui.progress(phase='captcha_wait', pause_until=time.time()+599, captcha_attempt=2)
                    expect(page.get_by_text('Капча: пауза 2 из 2', exact=True)).to_be_visible()
                    page.get_by_role('button', name='Заполнить сейчас', exact=True).click()
                    assert ui.commands.get(timeout=2)['action'] == 'captcha_now'
                    ui.progress(phase='idle', pause_until=None, captcha_attempt=0)
                    page.screenshot(path='/tmp/apply-qa-desktop.png', full_page=True)
                    page.set_viewport_size({'width': 390, 'height': 844})
                    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'), 'Mobile overflow'
                    page.screenshot(path='/tmp/apply-qa-mobile.png', full_page=True)
                    page.get_by_role('button', name='Как это работает', exact=True).click()
                    expect(page.get_by_role('dialog')).to_be_visible()
                    page.keyboard.press('Escape')
                    expect(page.get_by_role('dialog')).to_have_count(0)
                    assert not errors, errors
                    assert not any('/api/state' in url for url in requests), 'Client must use SSE, not polling'
                    assert any('/api/events' in url for url in requests)
                    assert not any('api.hh.ru' in url for url in requests)
                    browser.close()
            finally:
                ui.stop_requested.set()
                ui.commands.put({'action': 'stop'})
                server.should_exit = True
                with ui.changed:
                    ui.changed.notify_all()
                thread.join(timeout=18)
                sock.close()
    print('PASS: login/code, preview, settings, SSE progress, CAPTCHA retry, manual form controls, stop, history filters, mobile layout, keyboard dialog. No live HH requests.')


if __name__ == '__main__':
    run()
