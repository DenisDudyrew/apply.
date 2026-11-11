"""Offline checks: no browser launches and no applications are sent."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import hh_apply as app


class OfflineChecks(unittest.TestCase):
    def test_titles_accept_both_roles_and_reject_unrelated_jobs(self):
        for name in ("Системный аналитик (AI)", "Бизнес-аналитик", "Senior Business Analyst",
                     "Systems Analyst", "Fullstack-аналитик", "Fullstack Analyst",
                     "Fullstack-аналитик (Бизнес/Системный аналитик)"):
            self.assertTrue(app.analyst_title(name), name)
        for name in ("Аналитик данных", "Финансовый аналитик", "Python developer",
                     "System Administrator", "Business Development Manager"):
            self.assertFalse(app.analyst_title(name), name)

    def test_external_and_lookalike_addresses_are_rejected(self):
        self.assertTrue(app.hh_url("https://hh.ru/vacancy/1"))
        self.assertTrue(app.hh_url("https://spb.hh.ru/vacancy/1"))
        for url in ("https://hh.ru.evil.example/", "https://fakehh.ru/", "http://hh.ru/",
                    "javascript:alert(1)", "https://hh.ru@evil.example/"):
            self.assertFalse(app.hh_url(url), url)

    def test_journal_keeps_uncertain_attempts_and_separates_resumes(self):
        with tempfile.TemporaryDirectory() as directory:
            journal = app.Journal(Path(directory) / "state.sqlite3")
            vacancy = {"id": "1", "name": "Системный аналитик", "employer": {"name": "Компания"},
                       "alternate_url": "https://hh.ru/vacancy/1"}
            journal.put("resume-a", vacancy, "pending")
            self.assertEqual(journal.status("resume-a", "1"), "pending")
            self.assertIsNone(journal.status("resume-b", "1"))
            journal.put("resume-a", vacancy, "uncertain", "Проверить вручную")
            report = Path(directory) / "report.json"
            journal.export(report)
            rows = json.loads(report.read_text())
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["status"], "uncertain")
            journal.db.close()

    def test_discovery_deduplicates_queries_and_filters_names(self):
        payload = {"pages": 1, "items": [
            {"id": "1", "name": "Системный аналитик"},
            {"id": "2", "name": "Аналитик данных"},
            {"id": "3", "name": "Бизнес аналитик", "archived": True}]}
        with patch.object(app, "get_json", return_value=payload):
            result = app.discover({"queries": ["системный аналитик", "бизнес аналитик"],
                                   "pages_per_query": 1, "area": None})
        self.assertEqual([row["id"] for row in result], ["1"])


if __name__ == "__main__":
    unittest.main()
