"""Durable queue. An interrupted in-flight application is never re-sent automatically."""
import json
from pathlib import Path
import sqlite3
import time
import uuid


class QueueStore:
    def __init__(self, root):
        self.root = Path(root)
        self.db = sqlite3.connect(self.root / 'queue.sqlite3', timeout=5)
        self.db.row_factory = sqlite3.Row
        self.db.executescript('''CREATE TABLE IF NOT EXISTS runs (
            id TEXT PRIMARY KEY, resume_id TEXT, profile_id TEXT, config TEXT, max_count INTEGER,
            state TEXT, created REAL, updated REAL);
            CREATE TABLE IF NOT EXISTS queue_items (
            run_id TEXT, seq INTEGER, vacancy_id TEXT, payload TEXT, status TEXT, note TEXT,
            PRIMARY KEY (run_id, vacancy_id));''')
        self.db.commit()

    def create(self, vacancies, config, limit):
        identifier = uuid.uuid4().hex
        self.db.execute('INSERT INTO runs VALUES (?,?,?,?,?,?,?,?)',
            (identifier, config['resume_id'], config.get('_profile_id'), json.dumps(config, ensure_ascii=False), limit, 'active', time.time(), time.time()))
        self.db.executemany('INSERT INTO queue_items VALUES (?,?,?,?,?,?)',
            [(identifier, i, str(v['id']), json.dumps(v, ensure_ascii=False), 'queued', '') for i, v in enumerate(vacancies)])
        self.db.commit()
        return identifier

    def set_state(self, identifier, state):
        self.db.execute('UPDATE runs SET state=?, updated=? WHERE id=?', (state, time.time(), identifier))
        self.db.commit()

    def mark(self, identifier, vacancy, status, note=''):
        self.db.execute('UPDATE queue_items SET status=?,note=? WHERE run_id=? AND vacancy_id=?',
                        (status, note, identifier, str(vacancy['id'])))
        self.db.execute('UPDATE runs SET updated=? WHERE id=?', (time.time(), identifier))
        self.db.commit()

    def items(self, identifier):
        return [json.loads(row['payload']) for row in self.db.execute(
            'SELECT payload FROM queue_items WHERE run_id=? AND status=? ORDER BY seq', (identifier, 'queued'))]

    def get(self, identifier):
        row = self.db.execute('SELECT * FROM runs WHERE id=?', (identifier,)).fetchone()
        if row is None:
            raise ValueError('Очередь не найдена.')
        value = dict(row)
        value['config'] = json.loads(value['config'])
        counts = {r['status']: r['n'] for r in self.db.execute(
            'SELECT status, COUNT(*) n FROM queue_items WHERE run_id=? GROUP BY status', (identifier,))}
        value.update(sent=counts.get('sent', 0), remaining=counts.get('queued', 0),
                     attention=sum(counts.get(s, 0) for s in ('processing', 'uncertain', 'stopped')),
                     total=sum(counts.values()))
        return value

    def latest(self, resume_id):
        row = self.db.execute('SELECT id FROM runs WHERE resume_id=? ORDER BY created DESC LIMIT 1', (resume_id,)).fetchone()
        if row is None:
            return None
        value = self.get(row['id'])
        return {key: value[key] for key in ('id', 'state', 'sent', 'remaining', 'attention', 'total', 'max_count')}

    def recover(self, journal):
        for row in self.db.execute("SELECT * FROM queue_items WHERE status='processing'").fetchall():
            vacancy = json.loads(row['payload'])
            run = self.get(row['run_id'])
            status = journal.status(run['resume_id'], row['vacancy_id'])
            if status not in ('sent', 'already', 'review', 'uncertain', 'stopped'):
                status = 'uncertain'
                journal.put(run['resume_id'], vacancy, status, 'Приложение закрылось во время обработки. Проверьте отклик на hh.ru; автоматического повтора не будет.')
            self.mark(row['run_id'], vacancy, status, 'Восстановлено после закрытия приложения')
        self.db.execute("UPDATE runs SET state='paused' WHERE state='active'")
        self.db.commit()

    def close(self):
        self.db.close()
