"""Two cooldowns, read-only probes, then human input. Never solves a challenge."""
from urllib.parse import urlparse


class CaptchaGate:
    def __init__(self, client, ui, manual, seconds=600, attempts=2):
        self.client, self.ui, self.manual = client, ui, manual
        self.seconds, self.maximum = seconds, attempts
        self.attempts = 0
        self.latest_url = None

    def reset(self):
        self.attempts = 0
        self.latest_url = None

    def probe(self):
        # Do not recursively call ApiClient.get: that would enter this handler again.
        response = self.client.session.get('https://api.hh.ru/me',
            headers=self.client._default_headers(), allow_redirects=False, timeout=(10, 30))
        try:
            body = response.json()
        except ValueError:
            return False
        if response.status_code == 200 and body.get('is_applicant') is True:
            return True
        for error in body.get('errors', []):
            url = error.get('captcha_url')
            if url and urlparse(url).scheme == 'https' and (urlparse(url).hostname or '').endswith('.hh.ru'):
                self.latest_url = url
        return False

    def __call__(self, url):
        self.latest_url = url
        while self.attempts < self.maximum:
            self.attempts += 1
            self.ui.log(f'Капча hh.ru. Пауза 10 минут: {self.attempts} из {self.maximum}.')
            if not self.ui.wait_captcha(self.seconds, self.attempts):
                break  # The user chose to enter it now.
            try:
                if self.probe():
                    # The original request may still require a CAPTCHA. Its explicit
                    # rejection re-enters this same gate without resetting the counter.
                    self.ui.log('Запрос чтения доступен. Проверяем продолжение операции.')
                    return True
            except Exception:
                self.ui.log('Не удалось подтвердить доступ после паузы.')
        self.ui.log('Нужен ручной ввод капчи. Автоматические паузы завершены.')
        return self.manual(self.latest_url)


def install(client, ui):
    if getattr(client, '_apply_gate_installed', False) or client.captcha_handler is None:
        return
    gate = CaptchaGate(client, ui, client.captcha_handler)
    original_request = client.request
    client.captcha_handler = gate
    client._apply_gate_installed = True
    def request(*args, **kwargs):
        gate.reset()
        try:
            return original_request(*args, **kwargs)
        finally:
            ui.progress(captcha_attempt=0, pause_until=None)
    client.request = request
