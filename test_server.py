"""Local HTTP boundary and dashboard data; no network access to hh.ru."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from fastapi.testclient import TestClient
import hh_apply
import hh_auth
import ui
from server import create_app


class ServerChecks(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        (self.root / 'config.json').write_text(json.dumps({'resume_id': 'resume-test', 'resume_title': 'Системный аналитик', 'queries': ['системный аналитик']}))
        (self.root / 'candidates.json').write_text(json.dumps([{'id': str(i), 'title': 'Системный аналитик', 'company': 'Компания', 'url': f'https://hh.ru/vacancy/{i}'} for i in range(25)]))
        self.journal = hh_apply.Journal(self.root / 'state.sqlite3')
        for i, status in enumerate(('sent', 'review', 'uncertain', 'pending', 'stopped')):
            self.journal.put('resume-test', {'id': str(i), 'name': 'Системный аналитик', 'alternate_url': f'https://hh.ru/vacancy/{i}'}, status, 'Причина')
        self.before = deepcopy(dict(ui.state))
        self.root_patch = patch.object(ui, 'ROOT', self.root)
        self.root_patch.start()
        self.auth_patch = patch.object(hh_auth, 'status', return_value={'authenticated': True, 'name': 'Тестовый аккаунт'})
        self.auth_patch.start()
        ui.stop_requested.clear()
        ui.state.update(running=False, waiting=False, prompt_id=None, phase='idle')
        self.client = TestClient(create_app(runtime=ui, root=self.root), base_url='http://127.0.0.1')
        self.headers = {'X-Token': ui.TOKEN}

    def tearDown(self):
        self.client.close()
        self.journal.db.close()
        self.auth_patch.stop()
        self.root_patch.stop()
        ui.state.update(self.before)
        ui.stop_requested.clear()
        while not ui.commands.empty():
            ui.commands.get_nowait()
        self.temp.cleanup()

    def test_bootstrap_contains_real_journal_counts_and_no_hh_tokens(self):
        payload = self.client.get('/api/session').json()
        self.assertEqual(payload['state']['summary']['sent'], 1)
        self.assertEqual(payload['state']['summary']['attention'], 3)
        self.assertEqual(payload['state']['candidate_count'], 25)
        self.assertEqual(payload['state']['preferences']['limit'], 1000)
        self.assertNotIn('access_token', json.dumps(payload))

    def test_csrf_host_and_origin_boundaries(self):
        self.assertEqual(self.client.post('/api/action', json={'action': 'stop'}).status_code, 403)
        self.assertEqual(self.client.get('/api/state', headers={'Host': 'evil.example', **self.headers}).status_code, 400)
        self.assertEqual(self.client.post('/api/action', headers={**self.headers, 'Origin': 'https://evil.example'}, json={'action': 'stop'}).status_code, 403)
        self.assertEqual(self.client.get('/auth-profile/token.json').status_code, 404)
        self.assertEqual(self.client.get('/state.sqlite3').status_code, 404)

    def test_filter_attention_and_search_and_pagination(self):
        payload = self.client.get('/api/history?status=attention', headers=self.headers).json()
        self.assertEqual(payload['total'], 3)
        self.assertEqual(self.client.get('/api/history?q=developer', headers=self.headers).json()['total'], 0)
        payload = self.client.get('/api/candidates?page=2', headers=self.headers).json()
        self.assertEqual(len(payload['items']), 5)
        self.assertEqual(payload['total'], 25)

    def test_limits_are_validated_before_job_starts(self):
        for limit in (0, 1001, 2.5, True):
            response = self.client.post('/api/action', headers=self.headers, json={'action': 'start', 'limit': limit})
            self.assertEqual(response.status_code, 422)
        with patch.object(ui.threading, 'Thread') as thread:
            response = self.client.post('/api/action', headers=self.headers,
                json={'action': 'start', 'limit': 37, 'send': False, 'skip_questionnaires': False})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(thread.call_args.kwargs['args'][1], 37)
            self.assertFalse(thread.call_args.kwargs['args'][2]['skip_questionnaires'])
            self.assertEqual(ui.state['run']['limit'], 37)
            self.assertEqual(ui.preferences()['limit'], 37)

    def test_stale_captcha_answer_cannot_go_into_a_new_prompt(self):
        ui.state.update(waiting=True, prompt_id='new-prompt')
        response = self.client.post('/api/action', headers=self.headers,
            json={'action': 'answer', 'text': 'wrong-stale-code', 'prompt_id': 'old-prompt'})
        self.assertEqual(response.status_code, 409)
        self.assertTrue(ui.commands.empty())
        response = self.client.post('/api/action', headers=self.headers,
            json={'action': 'answer', 'text': '123456', 'prompt_id': 'new-prompt'})
        self.assertEqual(response.status_code, 200)
        self.assertNotIn('123456', json.dumps(dict(ui.state)))

    def test_active_job_is_not_replaced_by_second_launch(self):
        ui.state['running'] = True
        response = self.client.post('/api/action', headers=self.headers, json={'action': 'start'})
        self.assertEqual(response.status_code, 409)
        self.client.post('/api/action', headers=self.headers, json={'action': 'stop'})
        self.assertTrue(ui.stop_requested.is_set())
        self.assertEqual(ui.state['phase'], 'stopping')

    def test_progress_updates_stream_revision_and_counts(self):
        before = ui.state.revision
        ui.progress(total=17, phase='sending', current={'title': 'Тест'})
        ui.entry({}, 'sent', 'ok')
        self.assertGreater(ui.state.revision, before)
        value = self.client.get('/api/state', headers=self.headers).json()
        self.assertEqual(value['run']['total'], 17)
        self.assertEqual(value['run']['sent'], 1)
        self.assertEqual(value['phase'], 'sending')


if __name__ == '__main__':
    unittest.main()
