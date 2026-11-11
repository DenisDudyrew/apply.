"""Editable per-resume search profiles. No account tokens are stored here."""
import json
import re
import uuid
from pathlib import Path
from hh_auth import private_json


class Profiles:
    def __init__(self, root):
        self.root = Path(root)
        self.path = self.root / 'profiles.json'

    def read(self):
        if self.path.exists():
            return json.loads(self.path.read_text(encoding='utf-8'))
        config = json.loads((self.root / 'config.json').read_text(encoding='utf-8'))
        items = []
        if config.get('resume_id'):
            text = config.get('letter_text')
            if text is None:
                path = self.root / config.get('letter_file', 'letter.txt')
                text = path.read_text(encoding='utf-8') if path.exists() else ''
            items.append({'id': 'legacy', 'name': config['resume_title'], 'resume_id': config['resume_id'],
                          'resume_title': config['resume_title'], 'queries': config.get('queries', []),
                          'search_mode': config.get('search_mode', 'keywords'),
                          'letter_mode': config.get('letter_mode', 'required'), 'letter_text': text})
        return {'selected': items[0]['id'] if items else None, 'items': items}

    def save(self, data):
        private_json(self.path, data)

    def select(self, identifier):
        data = self.read()
        item = next((p for p in data['items'] if p['id'] == identifier), None)
        if item is None:
            raise ValueError('Профиль не найден.')
        config = json.loads((self.root / 'config.json').read_text(encoding='utf-8'))
        config.update({key: item[key] for key in ('resume_id', 'resume_title', 'queries', 'search_mode', 'letter_mode', 'letter_text')})
        config['_profile_id'] = item['id']
        private_json(self.root / 'config.json', config)
        if item.get('preferences'):
            private_json(self.root / 'ui-settings.json', item['preferences'])
        data['selected'] = identifier
        self.save(data)
        return item

    def upsert(self, values, resumes):
        data = self.read()
        old = next((p for p in data['items'] if p['id'] == values.get('profile_id')), None)
        resume = next((r for r in resumes if r['id'] == values['resume_id']), None)
        if resume is None and old and old['resume_id'] == values['resume_id']:
            resume = {'id': old['resume_id'], 'title': old['resume_title']}
        if resume is None:
            raise ValueError('Сначала загрузите список резюме и выберите своё резюме.')
        queries = [q.strip() for q in values.get('queries', []) if q.strip()]
        if not queries:
            queries = [re.sub(r'\s*\(.*', '', resume['title']).strip()]
        mode = values.get('letter_mode', 'required')
        text = values.get('letter_text', '').strip()
        if mode != 'none' and not text:
            raise ValueError('Введите шаблон сопроводительного письма.')
        item = {'id': old['id'] if old else uuid.uuid4().hex, 'name': values.get('profile_name', '').strip() or resume['title'],
                'resume_id': resume['id'], 'resume_title': resume['title'], 'queries': queries,
                'search_mode': values.get('search_mode', 'resume'), 'letter_mode': mode, 'letter_text': text,
                'preferences': {key: values.get(key, default) for key, default in {'limit': 1000, 'skip_questionnaires': True, 'skip_foreign_vacancies': True, 'gentle': True}.items()}}
        data['items'] = [p for p in data['items'] if p['id'] != item['id']] + [item]
        self.save(data)
        return self.select(item['id'])
