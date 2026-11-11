"""CAPTCHA controls act only on the site's challenge dialog."""
import unittest
from unittest.mock import Mock
import captcha_ui


class CaptchaControls(unittest.TestCase):
    def test_submit_targets_captcha_not_application(self):
        page = Mock()
        scope = page.get_by_role.return_value.first
        captcha_ui.submit(page, 'manual answer')
        scope.get_by_role.assert_any_call('textbox')
        scope.get_by_role.return_value.first.fill.assert_called_once_with('manual answer')
        scope.get_by_role.assert_any_call('button', name='Отправить', exact=True)
        page.goto.assert_not_called()
        page.reload.assert_not_called()

    def test_native_refresh_button_is_used(self):
        page = Mock()
        button = Mock()
        button.is_visible.return_value = True
        page.get_by_role.return_value.first.get_by_role.return_value.all.return_value = [button]
        self.assertTrue(captcha_ui.refresh(page))
        button.click.assert_called_once()
        page.reload.assert_not_called()

    def test_error_only_read_from_captcha_dialog(self):
        page = Mock()
        scope = page.get_by_role.return_value.first
        scope.is_visible.return_value = True
        scope.inner_text.return_value = 'Пройдите капчу\nНеверный текст капчи\nОтправить'
        self.assertEqual(captcha_ui.error_text(page), 'Неверный текст капчи')
        scope.is_visible.return_value = False
        self.assertEqual(captcha_ui.error_text(page), '')


if __name__ == '__main__':
    unittest.main()
