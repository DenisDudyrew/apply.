import unittest
from unittest.mock import Mock
from captcha_gate import CaptchaGate


class CooldownChecks(unittest.TestCase):
    def test_two_failed_checks_then_manual(self):
        ui, client = Mock(), Mock()
        ui.wait_captcha.return_value = True
        manual = Mock(return_value=True)
        gate = CaptchaGate(client, ui, manual)
        gate.probe = Mock(return_value=False)
        self.assertTrue(gate('https://hh.ru/captcha'))
        self.assertEqual(ui.wait_captcha.call_args_list[0].args, (600, 1))
        self.assertEqual(ui.wait_captcha.call_args_list[1].args, (600, 2))
        self.assertEqual(gate.probe.call_count, 2)
        manual.assert_called_once()

    def test_read_access_does_not_reset_attempt_budget(self):
        ui = Mock()
        ui.wait_captcha.return_value = True
        manual = Mock(return_value=True)
        gate = CaptchaGate(Mock(), ui, manual)
        gate.probe = Mock(return_value=True)
        gate('https://hh.ru/captcha')
        gate('https://hh.ru/captcha-new')
        gate('https://hh.ru/captcha-still-required')
        self.assertEqual(ui.wait_captcha.call_count, 2)
        manual.assert_called_once_with('https://hh.ru/captcha-still-required')

    def test_enter_now_skips_wait_and_does_not_probe(self):
        ui = Mock()
        ui.wait_captcha.return_value = False
        manual = Mock(return_value=True)
        gate = CaptchaGate(Mock(), ui, manual)
        gate.probe = Mock()
        gate('https://hh.ru/captcha')
        gate.probe.assert_not_called()
        manual.assert_called_once()

    def test_probe_uses_get_only(self):
        client = Mock()
        client.session.get.return_value.status_code = 200
        client.session.get.return_value.json.return_value = {'is_applicant': True}
        gate = CaptchaGate(client, Mock(), Mock())
        self.assertTrue(gate.probe())
        client.session.get.assert_called_once()
        client.post.assert_not_called()


if __name__ == '__main__':
    unittest.main()
