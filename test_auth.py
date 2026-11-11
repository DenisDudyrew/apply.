"""Authentication integration checks; no network or real SMS."""
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
import hh_auth
import ui


class AuthenticationChecks(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name) / 'auth-profile'
        self.patch = patch.object(hh_auth, 'AUTH_DIR', self.root)
        self.patch.start()
        while not ui.commands.empty():
            ui.commands.get_nowait()

    def tearDown(self):
        self.patch.stop()
        self.directory.cleanup()

    def saved_session(self):
        self.root.mkdir(exist_ok=True)
        hh_auth.private_json(self.root / 'token.json', {'token': {'access_token': 'private-token'}})
        hh_auth.private_json(self.root / 'identity.json', {'name': 'Тестовый соискатель'})

    def test_search_requires_login_and_does_not_send_anonymous_request(self):
        with patch.object(hh_auth, 'make_tool') as factory:
            with self.assertRaisesRegex(RuntimeError, 'Сначала'):
                hh_auth.get('/vacancies')
            factory.assert_not_called()

    def test_search_uses_authenticated_client_and_preserves_params(self):
        self.saved_session()
        tool = Mock()
        tool.api_client.get.return_value = {'items': []}
        with patch.object(hh_auth, 'make_tool', return_value=tool):
            self.assertEqual(hh_auth.get('/vacancies', {'text': 'аналитик'}), {'items': []})
        tool.api_client.get.assert_called_once_with('/vacancies', {'text': 'аналитик'})

    def test_dependency_client_attaches_saved_bearer_token(self):
        self.saved_session()
        hh_auth.private_json(self.root / 'token.json', {'token': {'access_token': 'USER_test_token'}})
        tool = hh_auth.make_tool()
        self.assertEqual(tool.api_client._default_headers()['Authorization'], 'Bearer USER_test_token')

    def test_login_uses_dependency_and_cleans_up_otp_input_hook(self):
        from hh_applicant_tool.operations import authorize
        tool = Mock()
        tool.get_me.return_value = {'id': '1', 'is_applicant': True, 'first_name': 'Тест'}
        panel = Mock()
        panel.prompt.return_value = '123456'
        before = getattr(authorize, 'input', None)

        def operation_run(tool_arg, args):
            self.assertIs(tool_arg, tool)
            self.assertEqual(args.username, 'test@example.test')
            self.assertIsNone(args.password)
            self.assertEqual(authorize.input('OTP'), '123456')
            hh_auth.private_json(self.root / 'token.json', {'token': {'access_token': 'USER_test'}})

        with patch.object(hh_auth, 'make_tool', return_value=tool), patch.object(authorize.Operation, 'run', side_effect=operation_run):
            result = hh_auth.authenticate('test@example.test', panel)
        self.assertTrue(result['authenticated'])
        self.assertEqual(getattr(authorize, 'input', None), before)
        tool.get_me.assert_called_once()

    def test_public_status_never_returns_tokens(self):
        self.saved_session()
        self.assertEqual(hh_auth.status(), {'authenticated': True, 'name': 'Тестовый соискатель'})
        self.assertNotIn('private-token', json.dumps(hh_auth.status()))
        if os.name != 'nt':  # Windows credentials use the system vault in desktop mode.
            self.assertEqual((self.root / 'token.json').stat().st_mode & 0o777, 0o600)

    def test_disconnect_removes_api_credentials(self):
        self.saved_session()
        hh_auth.disconnect()
        self.assertFalse(hh_auth.status()['authenticated'])
        self.assertFalse((self.root / 'token.json').exists())

    def test_one_time_code_stays_out_of_state_and_logs(self):
        ui.commands.put({'action': 'answer', 'text': '654321'})
        self.assertEqual(ui.prompt('Введите код'), '654321')
        self.assertNotIn('654321', json.dumps(ui.state))
        self.assertFalse(ui.state['waiting'])

    def test_captcha_input_can_be_cancelled(self):
        ui.commands.put({'action': 'stop'})
        with self.assertRaises(KeyboardInterrupt):
            ui.prompt('Капча', b'image')
        self.assertEqual(ui.state['image'], '')
        self.assertFalse(ui.state['waiting'])

    def test_browser_cookies_exclude_other_sites(self):
        from http.cookiejar import Cookie, MozillaCookieJar
        self.root.mkdir()
        jar = MozillaCookieJar(str(self.root / 'cookies.txt'))
        for domain in ('.hh.ru', 'hh.ru.evil.test'):
            jar.set_cookie(Cookie(0, 'test', 'secret', None, False, domain, True, True,
                                  '/', True, True, None, True, None, None, {}, False))
        jar.save(ignore_discard=True)
        cookies = hh_auth.browser_cookies()
        self.assertEqual([c['domain'] for c in cookies], ['.hh.ru'])


if __name__ == '__main__':
    unittest.main()
