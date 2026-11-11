"""Manual CAPTCHA controls: use the site's own form and refresh button."""
import re


def dialog(page):
    return page.get_by_role('dialog', name='Пройдите капчу').first


def is_open(page):
    return dialog(page).is_visible()


def error_text(page):
    scope = dialog(page)
    if not scope.is_visible():
        return ''
    for text in scope.inner_text().splitlines():
        if re.search(r'неверн|неправильн|не совпада|попробуйте.*(?:раз|снова)|ошибка', text, re.I):
            return text.strip()
    return ''


def submit(page, text):
    scope = dialog(page)
    field = scope.get_by_role('textbox').first
    field.fill(text)
    scope.get_by_role('button', name='Отправить', exact=True).click(timeout=5000)


def refresh(page):
    """Refresh only the challenge, never navigate/re-click the application."""
    scope = dialog(page)
    candidates = scope.get_by_role('button', name=re.compile(r'обнов|друг.*картин|refresh', re.I))
    for button in candidates.all():
        if button.is_visible():
            button.click(timeout=5000)
            return True
    # The current hh.ru refresh control is an unlabelled wide icon button.
    # The close icon is small; language/submit controls have text.
    for button in scope.get_by_role('button').all():
        box = button.bounding_box()
        if box and box['width'] >= 80 and not button.inner_text().strip():
            if not button.get_attribute('aria-label') and button.get_attribute('type') != 'submit':
                button.click(timeout=5000)
                return True
    return False
