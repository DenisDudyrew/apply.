"""Authenticated applications through hh-applicant-tool; browser only for manual forms."""
from contextlib import ExitStack
import random
import time
from urllib.parse import urlparse
import hh_auth


def country_index(areas):
    result = {}
    def visit(node, country):
        result[str(node['id'])] = country
        for child in node.get('areas', []):
            visit(child, country)
    for country in areas:
        visit(country, str(country['id']))
    return result


class Sender:
    def __init__(self, config, letter, ui=None):
        self.config, self.letter, self.ui = config, letter, ui
        self.tool = hh_auth.current_tool(ui)
        self.client = self.tool.api_client
        # A lost POST response must never cause an automatic network retry.
        self.client.max_retries = 1
        self.stack = ExitStack()
        self.page = None
        self.active_id = None
        self.active_started = None
        self.countries = {}
        self.resume_country = None
        self.tool.on_panel_captcha = self.captcha_event

    def captcha_event(self):
        import hh_apply
        hh_apply.record_event('captcha', transport='api', vacancy_id=self.active_id,
                              seconds_since_attempt=round(time.monotonic() - self.active_started, 1) if self.active_started else None,
                              pause_seconds=self.config.get('_last_pause'), gentle=self.config.get('gentle', False))
        if self.ui:
            self.ui.log('Капча API hh.ru: введите текст картинки в панели.')

    def verify(self):
        resumes = self.client.get('/resumes/mine').get('items', [])
        resume = next((r for r in resumes if str(r['id']) == self.config['resume_id']), None)
        if not resume or resume.get('title') != self.config['resume_title']:
            raise RuntimeError('Выбранное резюме не подтверждено в аккаунте. Проверьте его название и ID.')
        if not resume.get('area'):
            resume = self.client.get('/resumes/' + self.config['resume_id'])
        self.countries = country_index(self.client.get('/areas'))
        self.resume_country = self.countries.get(str((resume.get('area') or {}).get('id')))

    def browser(self, vacancy):
        import hh_apply
        if self.ui is None:
            return 'review', 'Требуется ручная форма: откройте панель управления'
        if self.page is None:
            from playwright.sync_api import sync_playwright
            engine = self.stack.enter_context(sync_playwright())
            from browser_runtime import launch_context
            context = launch_context(engine, hh_apply.ROOT / 'browser-profile', self.ui)
            self.stack.callback(context.close)
            cookies = hh_auth.browser_cookies()
            if cookies:
                context.add_cookies(cookies)
            self.page = context.pages[0] if context.pages else context.new_page()
            self.page.goto('https://hh.ru/resume/' + self.config['resume_id'], wait_until='domcontentloaded')
            self.ui.manual(self.page, 'Для ручной формы проверьте выбранное по умолчанию резюме: ' + self.config['resume_title'])
            if not hh_apply.hh_url(self.page.url) or not hh_apply.visible(
                    self.page.get_by_role('heading', name=self.config['resume_title'], exact=True)):
                return 'review', 'Не удалось подтвердить резюме для ручной формы'
        return hh_apply.send_one(self.page, vacancy, self.config, self.letter, self.ui)

    def send(self, vacancy):
        import hh_apply
        self.active_id = str(vacancy['id'])
        self.active_started = time.monotonic()
        try:
            detail = self.client.get('/vacancies/' + self.active_id)
        except Exception as error:
            if getattr(error, 'status_code', None) == 404:
                return 'review', 'Вакансия закрыта или недоступна'
            return 'stopped', 'Не удалось прочитать вакансию через API; отправка не выполнялась'
        item = dict(vacancy, **detail)
        if item.get('archived') or not hh_apply.matches_title(item.get('name', ''), self.config):
            return 'review', 'Вакансия закрыта или название больше не соответствует поиску'
        if 'got_response' in (item.get('relations') or []):
            return 'already', 'API подтверждает существующий отклик'
        country = self.countries.get(str((item.get('area') or {}).get('id')))
        if not country or not self.resume_country:
            if self.config.get('skip_foreign_vacancies', True):
                return 'review', 'Не удалось определить страну вакансии или резюме; пропущено'
            return self.browser(item)
        if country != self.resume_country:
            if self.config.get('skip_foreign_vacancies', True):
                return 'review', 'Другая страна: пропущено по настройке «Без вакансий в другой стране»'
            return self.browser(item)
        if item.get('has_test'):
            if self.config.get('skip_questionnaires', True):
                return 'review', 'Анкета пропущена по настройке «Без анкет»'
            return self.browser(item)
        payload = {'resume_id': self.config['resume_id'], 'vacancy_id': self.active_id}
        if item.get('response_letter_required') is True and self.config.get('letter_mode') == 'none':
            return 'review', 'Сопроводительное письмо обязательно, но выключено в профиле'
        if item.get('response_letter_required') is True or self.config.get('letter_mode') == 'always':
            payload['message'] = self.letter.replace('{resume}', self.config['resume_title']).replace('{vacancy}', item['name']).replace(
                '{company}', (item.get('employer') or {}).get('name', 'компании')).replace('{resume}', self.config['resume_title'])
        codes = []
        def capture(response, **kwargs):
            if response.request.method == 'POST' and urlparse(response.url).path == '/negotiations':
                codes.append(response.status_code)
        hooks = self.client.session.hooks.setdefault('response', [])
        hooks.append(capture)
        try:
            if self.ui:
                self.ui.check_stop()
            result = self.client.post('/negotiations', payload)
            if codes and codes[-1] in (201, 204) and result == {}:
                return 'sent', f'API hh.ru подтвердил создание отклика (HTTP {codes[-1]})'
            return 'uncertain', 'Неожиданный ответ API после отправки; автоматический повтор запрещён'
        except Exception as error:
            code = getattr(error, 'status_code', None)
            data = getattr(error, 'data', {})
            values = {str(e.get('value', '')) for e in data.get('errors', [])} if isinstance(data, dict) else set()
            if code in (400, 403) and 'already_applied' in values:
                return 'already', 'API сообщил, что отклик уже существует'
            if code == 429 or any('limit' in v for v in values):
                return 'stopped', 'Достигнут лимит hh.ru; запуск остановлен'
            if code == 403:
                return 'stopped', 'API hh.ru отказал в отправке. Требуется проверка доступа или капчи'
            if code in (400, 404):
                return 'review', 'API отклонил форму отклика; нужна ручная проверка (' + ', '.join(sorted(values)) + ')'
            return 'uncertain', 'Нет надёжного ответа API после отправки; автоматический повтор запрещён'
        finally:
            hooks.remove(capture)

    def close(self):
        self.tool.on_panel_captcha = None
        self.stack.close()


def run(queue, journal, config, letter, limit, ui=None):
    import hh_apply
    output = ui.log if ui else print
    completed = 0
    sender = None
    from queue_store import QueueStore
    store = QueueStore(hh_apply.ROOT)
    run_id = config.get('_queue_run_id') or store.create(queue, dict(config, letter_text=letter), limit)
    completed = store.get(run_id)['sent']
    store.set_state(run_id, 'active')
    if ui:
        ui.progress(queue_id=run_id, sent=completed)
    with hh_auth.locked():
        try:
            sender = Sender(config, letter, ui)
            if ui:
                ui.progress(phase='verifying')
            sender.verify()
            output('Отклики через авторизованный API. Резюме проверено: ' + config['resume_title'])
            for number, vacancy in enumerate(queue, 1):
                if ui:
                    ui.check_stop()
                if completed >= limit:
                    break
                if vacancy.get('has_test') and config.get('skip_questionnaires', True):
                    journal.put(config['resume_id'], vacancy, 'review', 'Анкета пропущена по настройке')
                    store.mark(run_id, vacancy, 'review', 'Анкета пропущена по настройке')
                    if ui:
                        ui.entry(vacancy, 'review', 'Анкета пропущена по настройке')
                    continue
                if ui:
                    ui.progress(phase='sending', current={'title': vacancy['name'], 'company': (vacancy.get('employer') or {}).get('name', ''), 'url': vacancy['alternate_url']}, pause_until=None)
                output(f"[{completed}/{limit}] {vacancy['name']} — {(vacancy.get('employer') or {}).get('name', '')}")
                store.mark(run_id, vacancy, 'processing')
                journal.put(config['resume_id'], vacancy, 'pending', 'Начата обработка; не повторять автоматически')
                hh_apply.record_event('attempt', transport='api', vacancy_id=str(vacancy['id']),
                                      attempt_number=number, pause_seconds=config.get('_last_pause'))
                status, note = sender.send(vacancy)
                journal.put(config['resume_id'], vacancy, status, note)
                store.mark(run_id, vacancy, status, note)
                journal.export(hh_apply.ROOT / 'report.json')
                if ui:
                    ui.entry(vacancy, status, note)
                output(f'{status}: {note}')
                if status == 'sent':
                    completed += 1
                if status in ('uncertain', 'stopped'):
                    if ui:
                        ui.progress(phase='error' if status == 'uncertain' else 'stopped')
                        ui.progress(message=note)
                    output('Запуск остановлен. Повторной отправки не будет.')
                    break
                if completed >= limit or number >= len(queue):
                    break
                pause = max(config['pause_seconds'], random.uniform(30, 60)) if config.get('gentle') else config['pause_seconds']
                config['_last_pause'] = round(pause, 1)
                output(f'Пауза {pause:.0f} с')
                if ui:
                    ui.progress(phase='pausing', pause_until=time.time() + pause)
                deadline = time.monotonic() + pause
                while time.monotonic() < deadline:
                    if ui:
                        ui.check_stop()
                    time.sleep(.25)
        finally:
            store.set_state(run_id, 'completed' if completed >= limit or not store.items(run_id) else 'paused')
            store.close()
            if sender:
                sender.close()
            journal.export(hh_apply.ROOT / 'report.json')
            output(f'Подтверждено новых отправок: {completed}/{limit}. Отчёт: report.json')
