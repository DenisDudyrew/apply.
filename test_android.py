"""Offline checks for the standalone Android adapter. No live HH requests."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

spec = importlib.util.spec_from_file_location('android_adapter_test', Path(__file__).parent / 'android/app/src/main/python/android_runtime.py')
android = importlib.util.module_from_spec(spec)
spec.loader.exec_module(android)


class AndroidChecks(unittest.TestCase):
    def setUp(self):
        self.host = Mock()
        self.host.encryptLogin.return_value = 'native-rsa'
        self.host.readSecret.return_value = '{}'
        self.tool = Mock()
        self.tool.xsrf_token = 'csrf'
        self.tool.parse_initial_state.return_value = {'xsrfToken': 'csrf', 'loginTrustFlagsSecret': 'public-key'}
        page = Mock(url='https://hh.ru/account/login?backurl=%2Foauth%2Fauthorize')
        callback = Mock(status_code=302, headers={'location': 'hhandroid://oauthresponse?code=test-code'})
        self.tool.session.get.side_effect = [page, callback]
        self.tool.xhr_request.side_effect = [{'success': True}, {'success': True, 'verification': {'success': True}}]
        self.tool.get_me.return_value = {'is_applicant': True, 'first_name': 'Test', 'id': 'test-user'}
        self.panel = Mock()
        self.panel.prompt.return_value = '123456'

    def test_otp_uses_native_crypto_and_verifies_identity(self):
        import hh_auth
        with tempfile.TemporaryDirectory() as directory, patch.object(android, '_host', self.host), \
             patch.object(hh_auth, 'AUTH_DIR', Path(directory)), patch.object(hh_auth, 'status', return_value={'authenticated': True}), \
             patch.object(android.time, 'sleep'):
            self.assertTrue(android.authorize('test@example.test', self.panel, Mock(return_value=self.tool))['authenticated'])
            self.assertEqual(self.host.encryptLogin.call_count, 2)
            self.tool.api_client.oauth_client.authenticate.assert_called_once_with('test-code')
            self.assertEqual(self.tool.xhr_request.call_args_list[1].kwargs['data']['code'], '123456')
            self.tool.save_cookies.assert_called_once()
            self.assertTrue((Path(directory) / 'identity.json').is_file())
            self.host.writeSecret.assert_not_called()

    def test_wrong_code_clears_credentials_and_does_not_exchange_token(self):
        import hh_auth
        self.tool.xhr_request.side_effect = [{'success': True}, {'success': False}]
        with tempfile.TemporaryDirectory() as directory, patch.object(android, '_host', self.host), \
             patch.object(hh_auth, 'AUTH_DIR', Path(directory)), patch.object(android.time, 'sleep'):
            with self.assertRaises(RuntimeError):
                android.authorize('test@example.test', self.panel, Mock(return_value=self.tool))
            self.host.writeSecret.assert_called_once_with('{}')
            self.tool.api_client.oauth_client.authenticate.assert_not_called()
            self.assertFalse((Path(directory) / 'identity.json').exists())

    def test_foreign_login_redirect_is_rejected(self):
        import hh_auth
        self.tool.session.get.side_effect = [Mock(url='https://example.test/login')]
        with tempfile.TemporaryDirectory() as directory, patch.object(android, '_host', self.host), \
             patch.object(hh_auth, 'AUTH_DIR', Path(directory)):
            with self.assertRaises(RuntimeError):
                android.authorize('test@example.test', self.panel, Mock(return_value=self.tool))
            self.tool.xhr_request.assert_not_called()

    def test_android_never_opens_desktop_browser_for_questionnaire(self):
        import api_apply
        with patch.dict('os.environ', APPLY_ANDROID='1'):
            sender = object.__new__(api_apply.Sender)
            self.assertEqual(sender.browser({'id': '1'})[0], 'review')

    def test_foreground_failure_prevents_dispatch(self):
        self.host.beginWork.side_effect = RuntimeError('Foreground denied')
        with patch.object(android, '_host', self.host), patch('ui.dispatch') as dispatch:
            result = json.loads(android.request('/api/action', json.dumps({'action': 'start', 'send': True})))
            self.assertFalse(result['ok'])
            dispatch.assert_not_called()

    def test_minimal_api_tool_does_not_need_desktop_extras(self):
        import builtins
        import hh_auth
        original_import = builtins.__import__
        def restricted_import(name, *args, **kwargs):
            if name.split('.')[0] in {'cryptography', 'PIL', 'playwright', 'fastapi', 'keyring'}:
                raise ImportError('Desktop-only package excluded from APK')
            return original_import(name, *args, **kwargs)
        with patch.dict('os.environ', APPLY_ANDROID='1'), tempfile.TemporaryDirectory() as directory, patch.object(hh_auth, 'AUTH_DIR', Path(directory)), \
             patch('secret_store.load', return_value={}), patch('builtins.__import__', side_effect=restricted_import):
            tool = hh_auth.make_tool()
            tool.session.close()
            tool.webview_session.close()
            tool.api_client.session.close()


if __name__ == '__main__':
    unittest.main()
