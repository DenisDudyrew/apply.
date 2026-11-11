import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
import hh_apply
from profiles import Profiles
from queue_store import QueueStore
from api_apply import Sender


class DesktopFeatures(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        (self.root / 'config.json').write_text(json.dumps({'resume_id': '', 'resume_title': '', 'queries': [], 'letter_file': 'letter.txt'}))
        (self.root / 'letter.txt').write_text('Шаблон')

    def tearDown(self):
        self.temp.cleanup()

    def test_profile_select_sets_resume_and_letter_without_tokens(self):
        profiles = Profiles(self.root)
        saved = profiles.upsert({'resume_id': 'r', 'profile_name': 'Мой профиль', 'letter_mode': 'always',
                                 'letter_text': 'Для {company}', 'search_mode': 'resume', 'queries': ['Python developer']},
                                [{'id': 'r', 'title': 'Python Developer'}])
        config = json.loads((self.root / 'config.json').read_text())
        self.assertEqual(config['resume_id'], 'r')
        self.assertEqual(config['letter_mode'], 'always')
        self.assertEqual(profiles.read()['selected'], saved['id'])
        self.assertNotIn('access_token', (self.root / 'profiles.json').read_text())

    def test_profile_cannot_invent_an_account_resume(self):
        with self.assertRaises(ValueError):
            Profiles(self.root).upsert({'resume_id': 'someone-else', 'letter_text': 'Письмо'}, [])

    def test_general_resume_titles_are_supported(self):
        config = {'search_mode': 'resume', 'queries': ['Python developer']}
        self.assertTrue(hh_apply.matches_title('Senior Python Developer', config))
        self.assertFalse(hh_apply.matches_title('Системный аналитик', config))
        config['queries'] = ['системный аналитик']
        self.assertTrue(hh_apply.matches_title('Системный аналитик (Middle)', config))
        self.assertFalse(hh_apply.matches_title('Бизнес-аналитик', config))

    def test_resume_discovery_uses_recommendations_and_title_filter(self):
        config = {'resume_id': 'r', 'search_mode': 'resume', 'queries': ['Python developer'], 'pages_per_query': 1}
        with patch.object(hh_apply, 'get_json', return_value={'pages': 1, 'items': [{'id': '1', 'name': 'Python developer'}, {'id': '2', 'name': 'Учитель'}]}) as get:
            result = hh_apply.discover(config)
        self.assertEqual(get.call_args.args[0], '/resumes/r/similar_vacancies')
        self.assertEqual([v['id'] for v in result], ['1'])

    def test_interrupted_inflight_is_not_queued_again(self):
        queue = QueueStore(self.root)
        journal = hh_apply.Journal(self.root / 'state.sqlite3')
        vacancy = {'id': '1', 'name': 'Системный аналитик', 'alternate_url': 'https://hh.ru/vacancy/1'}
        other = dict(vacancy, id='2')
        run = queue.create([vacancy, other], {'resume_id': 'r'}, 100)
        queue.mark(run, vacancy, 'processing')
        journal.put('r', vacancy, 'pending')
        queue.recover(journal)
        self.assertEqual([v['id'] for v in queue.items(run)], ['2'])
        self.assertEqual(journal.status('r', '1'), 'uncertain')
        self.assertEqual(queue.get(run)['attention'], 1)
        queue.close(); journal.db.close()

    def test_confirmed_send_is_reconciled_after_restart(self):
        queue = QueueStore(self.root)
        journal = hh_apply.Journal(self.root / 'state.sqlite3')
        vacancy = {'id': '1', 'name': 'Системный аналитик', 'alternate_url': 'https://hh.ru/vacancy/1'}
        run = queue.create([vacancy], {'resume_id': 'r'}, 100)
        queue.mark(run, vacancy, 'processing')
        journal.put('r', vacancy, 'sent')
        queue.recover(journal)
        self.assertEqual(queue.get(run)['sent'], 1)
        self.assertEqual(queue.get(run)['remaining'], 0)
        queue.close(); journal.db.close()

    def test_letter_none_never_sends_required_form(self):
        tool = Mock()
        tool.api_client.get.return_value = {'name': 'Системный аналитик', 'area': {'id': '1'}, 'response_letter_required': True}
        with patch('hh_auth.current_tool', return_value=tool):
            sender = Sender({'resume_id': 'r', 'resume_title': 'Системный аналитик', 'letter_mode': 'none'}, '')
            sender.countries = {'1': '113'}; sender.resume_country = '113'
            self.assertEqual(sender.send({'id': '1'})[0], 'review')
            tool.api_client.post.assert_not_called()
            sender.close()


if __name__ == '__main__':
    unittest.main()
