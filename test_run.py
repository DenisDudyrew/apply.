"""Run control regression: all queued jobs are processed without live requests."""
import itertools
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, MagicMock, patch
import hh_apply


class RunChecks(unittest.TestCase):
    def test_run_respects_configured_limit_above_thirty(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = {'resume_id': 'test', 'resume_title': 'Системный аналитик',
                      'max_applications': 1000, 'send_method': 'browser', 'pages_per_query': 1, 'pause_seconds': 3,
                      'letter_file': 'letter.txt'}
            (root / 'config.json').write_text(json.dumps(config))
            (root / 'letter.txt').write_text('Письмо')
            vacancies = [{'id': str(i), 'name': 'Системный аналитик',
                          'alternate_url': f'https://hh.ru/vacancy/{i}'} for i in range(40)]
            page = Mock(url='https://hh.ru/resume/test')
            context = Mock(pages=[page])
            engine = Mock()
            engine.chromium.launch_persistent_context.return_value = context
            manager = MagicMock()
            manager.__enter__.return_value = engine
            with patch.object(hh_apply, 'ROOT', root), \
                 patch.object(hh_apply, 'discover', return_value=vacancies), \
                 patch.object(hh_apply, 'visible', return_value=True), \
                 patch.object(hh_apply, 'send_one', return_value=('sent', 'confirmed')) as send, \
                 patch.object(hh_apply.time, 'monotonic', side_effect=itertools.count(0, 10)), \
                 patch('hh_auth.browser_cookies', return_value=[]), \
                 patch('playwright.sync_api.sync_playwright', return_value=manager):
                hh_apply.main(['--send', '--limit', '35'], ui=Mock())
            self.assertEqual(send.call_count, 35)
            report = json.loads((root / 'report.json').read_text())
            self.assertEqual(sum(row['status'] == 'sent' for row in report), 35)


if __name__ == '__main__':
    unittest.main()
