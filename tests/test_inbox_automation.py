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


class FakeDocumentAutomation:
    def __init__(self):
        self.attachments = None

    def run(self, attachments):
        self.attachments = attachments
        return {"review_ready": [], "analyzed_only": [{"document_id": 1}], "errors": []}


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

    def test_inbox_schedule_can_be_claimed_only_once_until_finished(self):
        configured = self.db.configure_inbox_schedule(True, 15, "AI-Operator", 10)
        claimed = self.db.claim_due_inbox_schedule()
        duplicate = self.db.claim_due_inbox_schedule()
        self.db.finish_inbox_schedule(result={"processed": []})

        self.assertEqual(configured["enabled"], 1)
        self.assertIsNotNone(claimed)
        self.assertIsNone(duplicate)
        self.assertEqual(self.db.get_inbox_schedule()["last_status"], "completed")

    def test_run_routes_attachments_to_document_automation(self):
        documents = FakeDocumentAutomation()
        result = InboxAutomation(self.db, FakeAnalyzer(), documents).run(
            [], attachments=[{"filename": "agreement.txt"}]
        )
        self.assertEqual(documents.attachments[0]["filename"], "agreement.txt")
        self.assertEqual(result["document_automation"]["analyzed_only"][0]["document_id"], 1)


if __name__ == "__main__":
    unittest.main()
