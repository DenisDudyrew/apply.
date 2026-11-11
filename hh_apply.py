#!/usr/bin/env python3
"""Authenticated HH API for discovery; visible browser for applications.

SMS/email login is provided by hh-applicant-tool. CAPTCHA answers are entered
by the user. Credentials stay locally and are sent only to hh.ru for access.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import random
import sqlite3
import time
from urllib.parse import urlencode, urlparse

from app_paths import DATA_DIR
ROOT = DATA_DIR
ROLE = re.compile(
    r"системн\w*\s+аналит\w*|бизнес[\s-]*аналит\w*|"
    r"business[\s/-]+analyst|systems?[\s/-]+analyst|"
    r"(?:full[\s-]*stack|фулл[\s-]*ст[еэ]к)[\s/-]+(?:аналит\w*|analyst)", re.I
)


def record_event(event, **details):
    with (ROOT / "timing-events.jsonl").open("a", encoding="utf-8") as stream:
        stream.write(json.dumps({"event": event, "time": datetime.now(timezone.utc).isoformat(),
                                 **details}, ensure_ascii=False) + "\n")


def analyst_title(title: str) -> bool:
    return bool(ROLE.search(title))


def matches_title(title: str, config: dict) -> bool:
    if not config.get('search_mode'):
        return analyst_title(title)
    normalized = re.sub(r'[^\w]+', ' ', title.lower()).strip()
    for query in config.get('queries', []):
        q = query.lower().strip()
        if re.fullmatch(r'системн\w*\s+аналит\w*', q):
            if re.search(r'системн\w*\s+аналит\w*|systems? analyst', title, re.I):
                return True
        elif re.fullmatch(r'бизнес[ -]*аналит\w*', q):
            if re.search(r'бизнес[ -]*аналит\w*|business analyst', title, re.I):
                return True
        elif all(word in normalized for word in re.findall(r'\w+', q)) and q:
            return True
    return False


def hh_url(url: str) -> bool:
    parsed = urlparse(url)
    host = parsed.hostname or ""
    return parsed.scheme == "https" and (host == "hh.ru" or host.endswith(".hh.ru"))


def get_json(path: str, params: dict | None = None, ui=None) -> dict:
    """Read-only API requests with the account authenticated in the panel."""
    import hh_auth
    return hh_auth.get(path, params, ui)


def discover(config: dict, ui=None) -> list[dict]:
    found = {}
    searches = config["queries"]
    if config.get('search_mode') == 'resume':
        searches = ['__resume__']
    for query in searches:
        for page in range(config["pages_per_query"]):
            if ui:
                ui.check_stop()
            params = {"text": query, "search_field": "name", "per_page": 100,
                      "page": page, "order_by": "publication_time"}
            if config.get("area"):
                params["area"] = str(config["area"])
            endpoint = '/vacancies'
            if query == '__resume__':
                endpoint = '/resumes/' + config['resume_id'] + '/similar_vacancies'
                params.pop('text', None)
            data = get_json(endpoint, params, ui)
            for item in data.get("items", []):
                if matches_title(item.get("name", ""), config) and not item.get("archived"):
                    found.setdefault(str(item["id"]), item)
            if page + 1 >= data.get("pages", 0):
                break
            time.sleep(0.5)
    return list(found.values())


class Journal:
    def __init__(self, path: Path):
        self.db = sqlite3.connect(path)
        self.db.execute("""CREATE TABLE IF NOT EXISTS applications (
            resume_id TEXT, vacancy_id TEXT, title TEXT, company TEXT, url TEXT,
            status TEXT, note TEXT, updated TEXT,
            PRIMARY KEY (resume_id, vacancy_id))""")
        self.db.commit()

    def status(self, resume: str, vacancy: str):
        row = self.db.execute("SELECT status FROM applications WHERE resume_id=? AND vacancy_id=?",
                              (resume, vacancy)).fetchone()
        return row[0] if row else None

    def put(self, resume: str, vacancy: dict, status: str, note: str = ""):
        self.db.execute("INSERT OR REPLACE INTO applications VALUES (?,?,?,?,?,?,?,?)", (
            resume, str(vacancy["id"]), vacancy["name"],
            (vacancy.get("employer") or {}).get("name", ""), vacancy["alternate_url"],
            status, note, datetime.now(timezone.utc).isoformat()))
        self.db.commit()

    def export(self, path: Path):
        self.db.row_factory = sqlite3.Row
        rows = self.db.execute("SELECT * FROM applications ORDER BY updated DESC").fetchall()
        path.write_text(json.dumps([dict(row) for row in rows], ensure_ascii=False, indent=2), encoding="utf-8")


def visible(locator) -> bool:
    try:
        return locator.first.is_visible()
    except Exception:
        return False


def sent(page) -> bool:
    # Similar-vacancy cards must never count as proof for the current vacancy.
    articles = page.get_by_role("article")
    scope = articles.first if articles.count() else page.get_by_role("main")
    return any(visible(scope.get_by_text(text, exact=True)) for text in
               ("Вы откликнулись", "Резюме доставлено", "Ваш отклик отправлен работодателю"))


def captcha(page) -> bool:
    return visible(page.get_by_role("dialog", name="Пройдите капчу")) or visible(
        page.get_by_role("textbox", name="Текст с картинки", exact=True))


def snapshot(page, vacancy_id: str, suffix: str):
    directory = ROOT / "screenshots"
    directory.mkdir(exist_ok=True)
    try:
        page.screenshot(path=str(directory / f"{vacancy_id}-{suffix}.png"))
    except Exception:
        pass


def send_one(page, vacancy: dict, config: dict, letter: str, ui=None) -> tuple[str, str]:
    """One application only. An ambiguous outcome stops the entire run."""
    import builtins
    print = ui.log if ui else builtins.print
    url = vacancy["alternate_url"]
    if not hh_url(url):
        return "review", "Внешний сайт: отклик вручную"
    page.goto(url, wait_until="domcontentloaded", timeout=60000)
    if not hh_url(page.url):
        return "review", "Переадресация за пределы hh.ru"
    if sent(page):
        return "already", "Отклик уже есть на сайте"
    page.get_by_role("heading", level=1).first.wait_for(timeout=15000)
    heading = page.get_by_role("heading", level=1).first.inner_text()
    if not matches_title(heading, config):
        return "review", "Название вакансии изменилось: проверьте вручную"
    # With a known test, do not submit half-complete questionnaires.
    if vacancy.get("has_test") and (ui is None or config.get("skip_questionnaires")):
        return "review", "Есть тест или анкета работодателя"

    buttons = page.get_by_role("button", name="Откликнуться", exact=True)
    if buttons.count() == 0:
        return "review", "Не найдена кнопка отклика; вакансия может быть закрыта"
    buttons.first.click(timeout=15000)
    deadline = time.monotonic() + 40
    form_submitted = False
    if ui and vacancy.get("has_test"):
        ui.manual(page, "Вакансия с анкетой: заполните ответы и отправьте форму на странице")
        form_submitted = True
        deadline = time.monotonic() + 40
    while time.monotonic() < deadline:
        if ui:
            ui.check_stop()
        if sent(page):
            snapshot(page, str(vacancy["id"]), "sent")
            return "sent", "Доставка подтверждена страницей hh.ru"
        if not hh_url(page.url):
            return "uncertain", "Внешняя переадресация после нажатия: проверить вручную"
        if captcha(page):
            record_event("captcha", vacancy_id=str(vacancy["id"]),
                         seconds_since_attempt=round(time.monotonic() - config.get("_attempt_time", time.monotonic()), 1),
                         pause_seconds=config.get("_last_pause"), attempt_number=config.get("_attempt_number"),
                         gentle=config.get("gentle", False))
            snapshot(page, str(vacancy["id"]), "captcha")
            print("\nКапча в браузере. Пройдите её вручную; скрипт не распознаёт и не обходит проверку.")
            if ui:
                ui.manual(page, "Введите текст капчи ниже и нажмите «Отправить капчу»", captcha_mode=True)
            else:
                input("Затем нажмите Enter здесь. Для остановки — Ctrl+C: ")
            deadline = time.monotonic() + 40
            # Never re-click Apply just because the challenge disappeared.
            continue
        country_warning = page.get_by_role("dialog").filter(
            has_text=re.compile(r"Вы откликаетесь на вакансию\s+в другой стране", re.I))
        if visible(country_warning):
            snapshot(page, str(vacancy["id"]), "country-review")
            if config.get("skip_foreign_vacancies", True):
                return "review", "Другая страна: пропущено по настройке «Без вакансий в другой стране»"
            if ui:
                ui.manual(page, "hh.ru предупреждает о другой стране. Если хотите откликнуться, подтвердите это кнопкой на странице, затем нажмите «Готово, продолжить»")
                deadline = time.monotonic() + 40
                continue
            return "review", "Для отклика в другой стране требуется ручное подтверждение"
        body = page.locator("body").inner_text()
        if re.search(r"лимит.*отклик|слишком много запросов|достигнут.*лимит", body, re.I):
            return "uncertain", "Лимит hh.ru: выполнение остановлено"
        if re.search(r"Для отклика необходимо ответить|Ответьте на вопросы|Заполните анкету|Вопросы работодателя", body, re.I):
            snapshot(page, str(vacancy["id"]), "questions")
            if config.get("skip_questionnaires"):
                return "review", "Анкета пропущена по настройке «Без анкет»"
            if ui:
                ui.manual(page, "Заполните анкету работодателя и отправьте её на странице")
                form_submitted = True
                deadline = time.monotonic() + 40
                continue
            return "review", "Требуется анкета: ответы автоматически не заполнялись"
        dialogs = page.get_by_role("dialog", name="Отклик на вакансию", exact=True)
        form = dialogs.first if visible(dialogs) else page.get_by_role("main")
        if not form_submitted and visible(form.get_by_role("textbox", name="Сопроводительное письмо", exact=True)):
            # Verify the selected resume before any extra submission.
            if config["resume_title"] not in form.inner_text():
                return "review", "В форме не подтверждено выбранное резюме"
            field = form.get_by_role("textbox", name="Сопроводительное письмо", exact=True)
            required = (vacancy.get("response_letter_required") is True or
                        "Сопроводительное письмо обязательное" in form.inner_text() or
                        field.get_attribute("required") is not None or
                        field.get_attribute("aria-required") == "true")
            if required and config.get('letter_mode') == 'none':
                return 'review', 'Сопроводительное письмо обязательно, но выключено в профиле'
            if required or config.get('letter_mode') == 'always':
                field.fill(letter.replace("{vacancy}", vacancy["name"]).replace(
                    "{company}", (vacancy.get("employer") or {}).get("name", "компании")))
            submit = form.get_by_role("button", name="Откликнуться", exact=True)
            if submit.count() != 1 or not submit.is_enabled():
                return "review", "Форма требует дополнительных данных"
            submit.click(timeout=15000)
            form_submitted = True
            deadline = time.monotonic() + 40
        elif form_submitted and visible(dialogs):
            text = dialogs.first.inner_text()
            if re.search(r"ошибк|обязательн.*поле|не удалось", text, re.I):
                snapshot(page, str(vacancy["id"]), "review")
                return "review", "Форма не принята: нужна ручная проверка"
        page.wait_for_timeout(500)
    snapshot(page, str(vacancy["id"]), "uncertain")
    return "uncertain", "Нет подтверждения отправки; автоматический повтор запрещён"


def main(argv=None, ui=None, options=None):
    import hh_auth
    with hh_auth.client_scope(ui):
        return run_main(argv, ui, options)


def run_main(argv=None, ui=None, options=None):
    import builtins
    print = ui.log if ui else builtins.print
    parser = argparse.ArgumentParser(description="Отклики hh.ru на системную и бизнес-аналитику")
    parser.add_argument("--send", action="store_true", help="Отправлять отклики. Без флага только подбор")
    parser.add_argument("--limit", type=int, help="Максимум подтверждённых откликов за запуск: 1–1000")
    args = parser.parse_args(argv)
    config = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
    config.update(options or {})
    if not config.get('resume_id'):
        raise RuntimeError('Сначала выберите резюме и сохраните профиль поиска.')
    limit = args.limit if args.limit is not None else config.get("max_applications", 1000)
    if not 1 <= limit <= 1000 or not 1 <= config["pages_per_query"] <= 20 or config["pause_seconds"] < 3:
        parser.error("Лимит должен быть от 1 до 1000; страниц 1–20; пауза не меньше 3 секунд")
    letter = config.get('letter_text')
    if letter is None:
        letter = (ROOT / config["letter_file"]).read_text(encoding="utf-8").strip()
    if not letter and config.get('letter_mode') != 'none':
        parser.error("Шаблон письма пуст")
    resume_run = config.get('_queue_run_id')
    if resume_run:
        from queue_store import QueueStore
        store = QueueStore(ROOT)
        try:
            saved = store.get(resume_run)
            config = dict(saved['config'], _queue_run_id=resume_run)
            letter = config.get('letter_text', letter)
            limit = saved['max_count']
            vacancies = store.items(resume_run)
        finally:
            store.close()
        print('Продолжаю сохранённую очередь без повторения неизвестных откликов…')
    else:
        print("Ищу вакансии через официальный API hh.ru…")
        vacancies = discover(config, ui)
    journal = Journal(ROOT / "state.sqlite3")
    queue = [v for v in vacancies if not journal.status(config["resume_id"], str(v["id"]))]
    if resume_run:
        from queue_store import QueueStore
        store = QueueStore(ROOT)
        try:
            for vacancy in vacancies:
                if journal.status(config['resume_id'], str(vacancy['id'])):
                    store.mark(resume_run, vacancy, 'already', 'Карточка уже обработана; повтор исключён')
        finally:
            store.close()
    (ROOT / "candidates.json").write_text(json.dumps([
        {"id": v["id"], "title": v["name"], "company": (v.get("employer") or {}).get("name"),
         "url": v["alternate_url"]} for v in queue], ensure_ascii=False, indent=2), encoding="utf-8")
    if ui:
        ui.progress(total=len(queue), phase="ready" if not args.send else "verifying")
    print(f"Подходящих новых карточек: {len(queue)}. План сохранён в candidates.json")
    if not args.send:
        print("Это просмотр. Для отправки: python hh_apply.py --send")
        journal.db.close()
        return

    from file_lock import acquire
    lock = acquire(ROOT / '.run.lock')

    if config.get("send_method", "api") == "api":
        from api_apply import run
        try:
            return run(queue, journal, config, letter, limit, ui)
        finally:
            lock.release()
            journal.db.close()

    from playwright.sync_api import sync_playwright
    completed = 0
    with sync_playwright() as playwright:
        context = playwright.chromium.launch_persistent_context(
            str(ROOT / "browser-profile"), headless=ui is not None, viewport={"width": 1280, "height": 900})
        import hh_auth
        cookies = hh_auth.browser_cookies()
        if cookies:
            context.add_cookies(cookies)
        page = context.pages[0] if context.pages else context.new_page()
        try:
            page.goto(f"https://hh.ru/resume/{config['resume_id']}", wait_until="domcontentloaded")
            print("\nПроверьте аккаунт и резюме в панели." if ui else "\nВойдите в hh.ru в открытом браузере. Проверьте аккаунт и резюме.")
            print("Для быстрых откликов сайт использует выбранное по умолчанию резюме.")
            print("Убедитесь, что выбрано: " + config["resume_title"])
            if ui:
                ui.manual(page, "Проверьте выбранное резюме на странице ниже. Если hh.ru запросит вход, выполните его здесь, затем нажмите «Готово, продолжить»")
            else:
                input("Когда всё готово, нажмите Enter здесь: ")
            if not hh_url(page.url):
                raise RuntimeError("Открыта страница вне hh.ru")
            own_resume = f"https://hh.ru/resume/{config['resume_id']}"
            page.goto(own_resume, wait_until="domcontentloaded")
            if not visible(page.get_by_role("heading", name=config["resume_title"], exact=True)):
                raise RuntimeError("Не удалось подтвердить вход и название вашего резюме")
            # Pass the selected resume through the same recommendation page as the site UI.
            page.goto("https://hh.ru/search/vacancy?" + urlencode({"resume": config["resume_id"]}),
                      wait_until="domcontentloaded")
            attempt_number = 0
            for vacancy in queue:
                if ui:
                    ui.check_stop()
                if completed >= limit:
                    break
                if vacancy.get("has_test") and (ui is None or config.get("skip_questionnaires")):
                    journal.put(config["resume_id"], vacancy, "review", "Требуется тест/анкета")
                    continue
                print(f"\n[{completed}/{limit}] {vacancy['name']} — {(vacancy.get('employer') or {}).get('name', '')}")
                journal.put(config["resume_id"], vacancy, "pending", "Начата обработка; не повторять автоматически")
                attempt_number += 1
                config["_attempt_time"] = time.monotonic()
                config["_attempt_number"] = attempt_number
                record_event("attempt", vacancy_id=str(vacancy["id"]), attempt_number=attempt_number,
                             pause_seconds=config.get("_last_pause"), gentle=config.get("gentle", False))
                try:
                    status, note = send_one(page, vacancy, config, letter, ui)
                except Exception:
                    status, note = "uncertain", "Ошибка браузера: проверьте скриншот и отклики вручную"
                    snapshot(page, str(vacancy["id"]), "error")
                journal.put(config["resume_id"], vacancy, status, note)
                journal.export(ROOT / "report.json")
                print(f"{status}: {note}")
                if status == "sent":
                    completed += 1
                if status == "uncertain":
                    print("Остановлено, чтобы не повторять отправку с неизвестным результатом.")
                    break
                pause = max(config["pause_seconds"], random.uniform(30, 60)) if config.get("gentle") else config["pause_seconds"]
                config["_last_pause"] = round(pause, 1)
                print(f"Пауза {pause:.0f} с")
                until = time.monotonic() + pause
                while time.monotonic() < until:
                    if ui:
                        ui.check_stop()
                    page.wait_for_timeout(250)
        finally:
            journal.export(ROOT / "report.json")
            print(f"\nПодтверждено новых отправок за запуск: {completed}/{limit}. Отчёт: report.json")
            context.close()
            lock.release()
            journal.db.close()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nОстановлено. Незавершённая отправка не будет повторена автоматически.")
    except (RuntimeError, OSError, ValueError) as error:
        raise SystemExit(str(error))
