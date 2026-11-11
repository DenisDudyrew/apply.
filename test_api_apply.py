"""API sending checks: no real requests, no employers contacted."""
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
import requests
from hh_applicant_tool.api.client import ApiClient
import api_apply
import hh_auth


class ApiSending(unittest.TestCase):
    def setUp(self):
        self.config = {'resume_id': 'resume-selected', 'resume_title': 'Системный аналитик',
                       'skip_foreign_vacancies': True, 'skip_questionnaires': True}
        self.vacancy = {'id': '1', 'name': 'Системный аналитик', 'area': {'id': '1'},
                        'alternate_url': 'https://hh.ru/vacancy/1', 'employer': {'name': 'Компания'}}
        self.client = Mock()
        self.client.session.hooks = {}
        self.client.get.return_value = self.vacancy
        self.tool = Mock(api_client=self.client)
        self.factory = patch.object(hh_auth, 'current_tool', return_value=self.tool)
        self.factory.start()
        self.sender = api_apply.Sender(self.config, 'Для {company}: {vacancy}', ui=Mock())
        self.sender.countries = {'1': '113', '2': '40'}
        self.sender.resume_country = '113'
        self.sender.browser = Mock(return_value=('review', 'manual form'))
        self.reply(201)

    def tearDown(self):
        self.sender.close()
        self.factory.stop()

    def reply(self, status, body=None):
        def respond(*args):
            response = SimpleNamespace(request=SimpleNamespace(method='POST'),
                                       url='https://api.hh.ru/negotiations', status_code=status)
            for hook in self.client.session.hooks['response']:
                hook(response)
            return {} if body is None else body
        self.client.post.side_effect = respond

    def test_explicit_resume_and_no_optional_letter(self):
        self.assertEqual(self.sender.send(self.vacancy)[0], 'sent')
        self.client.post.assert_called_once_with('/negotiations',
            {'resume_id': 'resume-selected', 'vacancy_id': '1'})
        self.assertEqual(self.client.max_retries, 1)
        self.assertEqual(self.client.session.hooks['response'], [])

    def test_required_letter_uses_template(self):
        self.client.get.return_value = dict(self.vacancy, response_letter_required=True)
        self.sender.send(self.vacancy)
        self.assertEqual(self.client.post.call_args.args[1]['message'], 'Для Компания: Системный аналитик')

    def test_empty_200_is_not_delivery_confirmation(self):
        self.reply(200)
        self.assertEqual(self.sender.send(self.vacancy)[0], 'uncertain')
        self.client.post.assert_called_once()

    def test_timeout_remains_uncertain_and_is_never_retried(self):
        self.client.post.side_effect = requests.Timeout()
        self.assertEqual(self.sender.send(self.vacancy)[0], 'uncertain')
        self.client.post.assert_called_once()
        self.sender.browser.assert_not_called()

    def test_actual_upstream_client_does_not_retry_lost_post(self):
        session = Mock()
        session.request.side_effect = requests.ConnectionError('lost response')
        client = ApiClient(session=session, max_retries=1)
        with self.assertRaises(requests.ConnectionError):
            client.post('/negotiations', {'resume_id': 'r', 'vacancy_id': 'v'})
        session.request.assert_called_once()

    def test_existing_response_is_skipped(self):
        self.client.get.return_value = dict(self.vacancy, relations=['got_response'])
        self.assertEqual(self.sender.send(self.vacancy)[0], 'already')
        self.client.post.assert_not_called()

    def test_country_checkbox_skips_or_opens_manual_form(self):
        self.client.get.return_value = dict(self.vacancy, area={'id': '2'})
        self.assertEqual(self.sender.send(self.vacancy)[0], 'review')
        self.sender.browser.assert_not_called()
        self.config['skip_foreign_vacancies'] = False
        self.sender.send(self.vacancy)
        self.sender.browser.assert_called_once()
        self.client.post.assert_not_called()

    def test_questionnaire_checkbox_skips_or_opens_manual_form(self):
        self.client.get.return_value = dict(self.vacancy, has_test=True)
        self.sender.send(self.vacancy)
        self.sender.browser.assert_not_called()
        self.config['skip_questionnaires'] = False
        self.sender.send(self.vacancy)
        self.sender.browser.assert_called_once()
        self.client.post.assert_not_called()

    def test_read_error_stops_before_post(self):
        self.client.get.side_effect = requests.Timeout()
        self.assertEqual(self.sender.send(self.vacancy)[0], 'stopped')
        self.client.post.assert_not_called()

    def test_one_session_is_reused_inside_run(self):
        self.factory.stop()
        try:
            with patch.object(hh_auth, 'make_tool', return_value=self.tool) as factory:
                with hh_auth.client_scope():
                    self.assertIs(hh_auth.current_tool(), hh_auth.current_tool())
                    factory.assert_called_once()
        finally:
            self.factory.start()


class ApiRunChecks(unittest.TestCase):
    def run_case(self, outcomes, limit):
        import itertools
        import json
        from contextlib import nullcontext
        from pathlib import Path
        import tempfile
        import hh_apply
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            journal = hh_apply.Journal(root / 'state.sqlite3')
            config = {'resume_id': 'r', 'resume_title': 'Системный аналитик', 'pause_seconds': 3}
            queue = [{'id': str(i), 'name': 'Системный аналитик',
                      'alternate_url': f'https://hh.ru/vacancy/{i}'} for i in range(5)]
            sender = Mock()
            sender.send.side_effect = outcomes
            with patch.object(api_apply, 'Sender', return_value=sender), \
                 patch.object(hh_auth, 'locked', return_value=nullcontext()), \
                 patch.object(hh_apply, 'ROOT', root), \
                 patch.object(hh_apply, 'record_event'), \
                 patch.object(api_apply.time, 'monotonic', side_effect=itertools.count(0, 100)):
                api_apply.run(queue, journal, config, 'Письмо', limit, ui=Mock())
            rows = json.loads((root / 'report.json').read_text())
            journal.db.close()
            return sender, rows

    def test_api_loop_stops_on_uncertain_and_exports_journal(self):
        sender, rows = self.run_case([('sent', 'ok'), ('uncertain', 'timeout'), ('sent', 'must not send')], 1000)
        self.assertEqual(sender.send.call_count, 2)
        self.assertEqual({row['status'] for row in rows}, {'sent', 'uncertain'})
        sender.close.assert_called_once()

    def test_api_loop_obeys_user_limit(self):
        sender, rows = self.run_case([('sent', 'ok')] * 5, 2)
        self.assertEqual(sender.send.call_count, 2)
        self.assertEqual(len(rows), 2)


if __name__ == '__main__':
    unittest.main()
