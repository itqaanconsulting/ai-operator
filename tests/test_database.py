import tempfile
import unittest
from pathlib import Path

from database import Database
from models import ActionStatus, EmailAnalysis, EmailRequest


class DatabaseTest(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.db = Database(str(Path(self.tempdir.name) / "test.db"))
        self.db.init()

    def tearDown(self):
        self.tempdir.cleanup()

    def test_analysis_creates_commitment_and_pending_action(self):
        request = EmailRequest(
            subject="Please confirm by Friday",
            body="Can you confirm by Friday whether we should proceed?",
            sender="jane@example.com",
            gmail_msg_id="gmail-1",
        )
        analysis = EmailAnalysis(
            category="decision",
            summary="Jane is requesting a decision.",
            contact_name="Jane",
            company_or_project="Project X",
            commitment_title="Provide a decision on Project X",
            deadline="2026-09-04",
            urgency="high",
            proposed_action="Review the proposal and reply to Jane.",
            suggested_reply="Hi Jane, I will get back to you by Friday.",
            confidence=0.94,
        )

        email_id, commitment_id, action_id = self.db.save_analysis(request, analysis)

        self.assertIsNotNone(email_id)
        self.assertIsNotNone(commitment_id)
        self.assertIsNotNone(action_id)
        actions = self.db.list_rows("proposed_actions", "pending_approval")
        self.assertEqual(len(actions), 1)
        self.assertEqual(actions[0]["action_type"], "draft_reply")

    def test_action_can_only_be_decided_once(self):
        request = EmailRequest(subject="Action required", body="Can you review this?")
        analysis = EmailAnalysis(
            category="task",
            summary="A review has been requested.",
            commitment_title="Review the request",
            proposed_action="Review the request.",
        )
        _, _, action_id = self.db.save_analysis(request, analysis)

        approved = self.db.decide_action(action_id, ActionStatus.APPROVED, "Approved")
        repeated = self.db.decide_action(action_id, ActionStatus.REJECTED, None)

        self.assertEqual(approved["status"], "approved")
        self.assertIsNone(repeated)

    def test_approved_action_can_only_be_claimed_once(self):
        request = EmailRequest(
            subject="Reply required", body="Can you reply?",
            sender="jane@example.com", gmail_msg_id="gmail-2"
        )
        analysis = EmailAnalysis(
            category="task", summary="A reply has been requested.",
            commitment_title="Reply to Jane", proposed_action="Create a reply draft.",
            suggested_reply="Hi Jane, approved."
        )
        _, _, action_id = self.db.save_analysis(request, analysis)
        self.db.decide_action(action_id, ActionStatus.APPROVED, None)

        claimed = self.db.claim_approved_action(action_id)
        duplicate = self.db.claim_approved_action(action_id)
        finished = self.db.finish_action(action_id, {"draft_id": "draft-1"})

        self.assertEqual(claimed["gmail_msg_id"], "gmail-2")
        self.assertIsNone(duplicate)
        self.assertEqual(finished["status"], "executed")
        self.assertIn("draft-1", finished["payload_json"])


if __name__ == "__main__":
    unittest.main()
