import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from database import Database
from models import EmailAnalysis, EmailRequest
from open_loops import OpenLoopMonitor, parse_deadline


class OpenLoopMonitorTest(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.db = Database(str(Path(self.tempdir.name) / "test.db"))
        self.db.init()

    def tearDown(self):
        self.tempdir.cleanup()

    def add_commitment(self, title, deadline):
        _, commitment_id, _ = self.db.save_analysis(
            EmailRequest(subject=title, body="Please handle this commitment."),
            EmailAnalysis(
                category="task",
                summary=title,
                company_or_project="Carrefour",
                commitment_title=title,
                deadline=deadline,
            ),
        )
        return commitment_id

    def test_monitor_creates_overdue_and_due_soon_actions_once(self):
        overdue_id = self.add_commitment("Overdue task", "2026-09-01")
        due_soon_id = self.add_commitment("Upcoming task", "2026-09-04")
        future_id = self.add_commitment("Future task", "2026-09-20")
        missing_id = self.add_commitment("Undated task", None)
        now = datetime(2026, 9, 2, 12, 0, tzinfo=timezone.utc)

        first = OpenLoopMonitor(self.db).run(3, now=now)
        second = OpenLoopMonitor(self.db).run(3, now=now)

        self.assertEqual(first["checked"], 4)
        self.assertEqual({item["commitment_id"] for item in first["created"]},
                         {overdue_id, due_soon_id})
        self.assertEqual(first["not_due"], [future_id])
        self.assertEqual(first["missing_deadline"], [missing_id])
        self.assertEqual(first["existing"], [])
        self.assertEqual(len(second["created"]), 0)
        self.assertEqual(len(second["existing"]), 2)

    def test_completing_commitment_closes_pending_monitor_action(self):
        commitment_id = self.add_commitment("Overdue task", "2026-09-01")
        now = datetime(2026, 9, 2, 12, 0, tzinfo=timezone.utc)
        result = OpenLoopMonitor(self.db).run(3, now=now)
        action_id = result["created"][0]["action_id"]

        completed = self.db.complete_commitment(commitment_id, "Handled by phone.")
        actions = self.db.list_rows("proposed_actions")

        self.assertEqual(completed["status"], "completed")
        action = next(item for item in actions if item["id"] == action_id)
        self.assertEqual(action["status"], "rejected")
        self.assertIn("Handled by phone", action["decision_note"])

    def test_deadline_parser_supports_dates_and_utc_timestamps(self):
        self.assertEqual(parse_deadline("2026-09-04").date().isoformat(), "2026-09-04")
        self.assertEqual(parse_deadline("2026-09-04T10:30:00Z").tzinfo, timezone.utc)


if __name__ == "__main__":
    unittest.main()
