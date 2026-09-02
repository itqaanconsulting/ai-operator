import tempfile
import unittest
from pathlib import Path

from database import Database
from models import ActionStatus, EmailAnalysis, EmailRequest, RecordDecisionRequest


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

    def test_emails_are_grouped_into_entity_context_and_timeline(self):
        first = EmailRequest(subject="Campaign", body="Please approve the campaign.")
        second = EmailRequest(subject="Follow-up", body="Is the campaign approved?")
        self.db.save_analysis(first, EmailAnalysis(
            category="decision", summary="Campaign approval requested.",
            company_or_project="Carrefour", commitment_title="Approve campaign",
            proposed_action="Review the campaign proposal."
        ))
        self.db.save_analysis(second, EmailAnalysis(
            category="follow_up", summary="Campaign decision follow-up.",
            company_or_project="carrefour", commitment_title="Reply with decision",
            proposed_action="Reply with the final decision."
        ))

        entities = self.db.list_entities()
        self.assertEqual(len(entities), 1)
        self.assertEqual(entities[0]["email_count"], 2)
        entity = self.db.get_entity("CARREFOUR")
        decision = self.db.add_decision(entity["id"], RecordDecisionRequest(
            title="Campaign direction", decision="Proceed with the campaign.",
            rationale="The forecast meets the target."
        ))
        context = self.db.entity_context(entity["id"])
        timeline = self.db.entity_timeline(entity["id"])

        self.assertEqual(decision["status"], "final")
        self.assertEqual(len(context["emails"]), 2)
        self.assertEqual(len(context["commitments"]), 2)
        self.assertEqual(len(context["decisions"]), 1)
        self.assertIn("decision", {event["type"] for event in timeline["events"]})

    def test_decision_source_must_belong_to_entity(self):
        self.db.save_analysis(
            EmailRequest(subject="A", body="One"),
            EmailAnalysis(category="information", summary="One", company_or_project="Alpha"),
        )
        unrelated_email_id, _, _ = self.db.save_analysis(
            EmailRequest(subject="B", body="Two"),
            EmailAnalysis(category="information", summary="Two", company_or_project="Beta"),
        )
        alpha = self.db.get_entity("Alpha")

        with self.assertRaisesRegex(ValueError, "not linked"):
            self.db.add_decision(alpha["id"], RecordDecisionRequest(
                title="Invalid source", decision="Do something", source_email_id=unrelated_email_id
            ))


if __name__ == "__main__":
    unittest.main()
