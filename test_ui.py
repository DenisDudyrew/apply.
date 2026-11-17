"""Checks for manual handoff and cancellation without submitting real applications."""
import unittest
from unittest.mock import Mock
import ui
import hh_apply
from unittest.mock import patch


class PanelChecks(unittest.TestCase):
    def setUp(self):
        while not ui.commands.empty():
            ui.commands.get_nowait()

    def test_manual_input_click_and_resume(self):
        page = Mock()
        page.screenshot.return_value = b'jpeg'
        for action in ({'action': 'click', 'x': 50, 'y': 80},
                       {'action': 'text', 'text': 'Ответ пользователя'},
                       {'action': 'continue'}):
            ui.commands.put(action)
        ui.manual(page, 'Анкета')
        page.mouse.click.assert_called_once_with(50.0, 80.0)
        page.keyboard.insert_text.assert_called_once_with('Ответ пользователя')
        self.assertFalse(ui.state['waiting'])
        self.assertEqual(ui.state['image'], '')

    def test_stop_during_captcha_clears_manual_state(self):
        page = Mock()
        page.screenshot.return_value = b'jpeg'
        ui.commands.put({'action': 'stop'})
        with self.assertRaises(KeyboardInterrupt):
            ui.manual(page, 'Капча')
        self.assertFalse(ui.state['waiting'])

    def test_known_questionnaire_skipped_without_clicking_apply(self):
        page = Mock()
        page.get_by_role.return_value.first.inner_text.return_value = "Системный аналитик"
        page.url = "https://hh.ru/vacancy/1"
        vacancy = {"id": "1", "alternate_url": page.url, "has_test": True}
        with patch.object(hh_apply, "sent", return_value=False):
            status, note = hh_apply.send_one(page, vacancy, {"skip_questionnaires": True}, "", ui=Mock())
        self.assertEqual(status, "review")
        page.get_by_role.return_value.first.click.assert_not_called()

    def test_stop_between_vacancies(self):
        ui.commands.put({'action': 'stop'})
        with self.assertRaises(KeyboardInterrupt):
            ui.check_stop()

    def test_send_announces_start_and_confirmed_count(self):
        saved_state = dict(ui.state)
        try:
            ui.reset_run(2, 'send')
            with patch.object(hh_apply, 'main') as main, patch.object(ui, 'announce') as announce:
                main.side_effect = lambda *args, **kwargs: ui.progress(sent=2)
                ui.worker(True, 2, {})
            self.assertEqual(announce.call_args_list[0].args[0], 'Отклики запущены')
            self.assertEqual(announce.call_args_list[-1].args,
                             ('Отклики завершены', 'Подтверждено откликов: 2. Проверьте итог в Apply.'))
        finally:
            ui.state.clear()
            ui.state.update(saved_state)

    def test_failed_run_notice_does_not_expose_exception_payload(self):
        saved_state = dict(ui.state)
        try:
            ui.reset_run(2, 'send')
            with patch.object(hh_apply, 'main', side_effect=RuntimeError('private payload')), patch.object(ui, 'announce') as announce:
                ui.worker(True, 2, {})
            self.assertEqual(announce.call_args_list[-1].args[0], 'Запуск требует внимания')
            self.assertNotIn('private payload', str(announce.call_args_list))
        finally:
            ui.state.clear()
            ui.state.update(saved_state)


if __name__ == '__main__':
    unittest.main()
