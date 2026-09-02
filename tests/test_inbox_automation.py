import tempfile
import unittest
from pathlib import Path

from database import Database
from inbox_automation import InboxAutomation
from models import EmailAnalysis, EmailRequest


class FakeAnalyzer:
    def analyze(self, email):
        return EmailAnalysis(
            category="task",
            summary=f"AI analyzed {email.subject}",
            company_or_project="Carrefour",
            commitment_title="Reply to Carrefour",
            deadline="2026-09-03",
            urgency="high",
            proposed_action="Prepare a reply.",
            suggested_reply="Thanks, we will follow up.",
        )


class InboxAutomationTest(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.db = Database(str(Path(self.tempdir.name) / "test.db"))
        self.db.init()

    def tearDown(self):
        self.tempdir.cleanup()

    def test_run_analyzes_new_mail_skips_duplicates_and_monitors_open_loops(self):
        emails = [EmailRequest(subject="Action needed", body="Please reply.", gmail_msg_id="m-1")]
        automation = InboxAutomation(self.db, FakeAnalyzer())

        first = automation.run(emails)
        second = automation.run(emails)

        self.assertEqual(len(first["processed"]), 1)
        self.assertEqual(first["open_loop_monitor"]["checked"], 1)
        self.assertEqual(second["skipped"], ["m-1"])
        self.assertEqual(len(second["processed"]), 0)


if __name__ == "__main__":
    unittest.main()
