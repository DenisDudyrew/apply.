"""Local read-only views shared by desktop and Android."""
from datetime import datetime
import json
from pathlib import Path
import sqlite3
from zoneinfo import ZoneInfo


class Repository:
    def __init__(self, root):
        self.root = Path(root)
        self.candidate_stamp = None
        self.candidates = []

    def config(self):
        return json.loads((self.root / 'config.json').read_text(encoding='utf-8'))

    def connect(self):
        path = self.root / 'state.sqlite3'
        if not path.exists():
            return None
        db = sqlite3.connect(path.as_uri() + '?mode=ro', uri=True, timeout=2)
        db.row_factory = sqlite3.Row
        return db

    def history(self, status='', query='', page=1, size=20):
        db = self.connect()
        if db is None:
            return {'items': [], 'total': 0, 'page': page, 'size': size}
        try:
            where = 'resume_id=?'
            params = [self.config()['resume_id']]
            if status == 'attention':
                where += " AND status IN ('pending', 'uncertain', 'stopped')"
            elif status:
                where += ' AND status=?'
                params.append(status)
            if query:
                where += ' AND (title LIKE ? OR company LIKE ?)'
                params += [f'%{query}%', f'%{query}%']
            count = db.execute(f'SELECT COUNT(*) FROM applications WHERE {where}', params).fetchone()[0]
            rows = db.execute(f'SELECT * FROM applications WHERE {where} ORDER BY updated DESC LIMIT ? OFFSET ?',
                              params + [size, (page - 1) * size]).fetchall()
            return {'items': [dict(row) for row in rows], 'total': count, 'page': page, 'size': size}
        finally:
            db.close()

    def summary(self):
        db = self.connect()
        result = {'sent': 0, 'skipped': 0, 'already': 0, 'attention': 0, 'today_sent': 0}
        if db is None:
            return result
        today = datetime.now(ZoneInfo('Europe/Moscow')).date()
        try:
            rows = db.execute('SELECT status, updated FROM applications WHERE resume_id=?',
                              (self.config()['resume_id'],)).fetchall()
            for row in rows:
                key = {'sent': 'sent', 'review': 'skipped', 'already': 'already'}.get(row['status'], 'attention')
                result[key] += 1
                if row['status'] == 'sent':
                    try:
                        if datetime.fromisoformat(row['updated']).astimezone(ZoneInfo('Europe/Moscow')).date() == today:
                            result['today_sent'] += 1
                    except ValueError:
                        pass
            return result
        finally:
            db.close()

    def candidate_list(self, query='', page=1, size=20):
        path = self.root / 'candidates.json'
        if path.exists():
            stamp = (path.stat().st_mtime_ns, path.stat().st_size)
            if stamp != self.candidate_stamp:
                try:
                    self.candidates = json.loads(path.read_text(encoding='utf-8'))
                    self.candidate_stamp = stamp
                except (OSError, ValueError):
                    pass  # A write may be in progress; keep the last complete snapshot.
        items = [item for item in self.candidates if not query or query.lower() in
                 (item.get('title', '') + ' ' + (item.get('company') or '')).lower()]
        return {'items': items[(page - 1) * size:page * size], 'total': len(items), 'page': page, 'size': size}
