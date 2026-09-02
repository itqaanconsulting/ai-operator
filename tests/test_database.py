import tempfile
import unittest
from pathlib import Path

from database import Database
from models import (
    ActionStatus, EmailAnalysis, EmailRequest, EmailWorkItem, OperatorPlan, OperatorPlanStep,
    RecordDecisionRequest,
)


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

    def test_one_email_can_create_multiple_scenario_work_items(self):
        analysis = EmailAnalysis(
            category="task", scenario="finance", summary="Payment and reply needed.",
            work_items=[
                EmailWorkItem(kind="payment", title="Pay invoice", proposed_action="Review payment"),
                EmailWorkItem(kind="follow_up", title="Confirm payment", proposed_action="Draft confirmation", suggested_reply="Confirmed."),
            ],
        )
        email_id, _, _ = self.db.save_analysis(
            EmailRequest(subject="Invoice", body="Please pay and confirm."), analysis
        )
        commitments = [row for row in self.db.list_rows("commitments") if row["email_id"] == email_id]
        actions = [row for row in self.db.list_rows("proposed_actions") if row["email_id"] == email_id]
        self.assertEqual(len(commitments), 2)
        self.assertEqual(len(actions), 2)
        self.assertIn('"scenario": "finance"', actions[0]["payload_json"])
        queue = self.db.list_work_queue()
        self.assertEqual(len(queue), 1)
        self.assertEqual(queue[0]["email"]["subject"], "Invoice")
        self.assertEqual(len(queue[0]["commitments"]), 2)

    def test_meeting_work_item_creates_calendar_proposal_action(self):
        analysis = EmailAnalysis(
            category="meeting", scenario="meeting", summary="Meeting requested.",
            work_items=[EmailWorkItem(
                kind="meeting", title="Project review", proposed_action="Create meeting",
                start_at="2026-09-18T10:00:00+02:00", end_at="2026-09-18T10:30:00+02:00",
                attendees=["jane@example.com"],
            )],
        )
        _, _, action_id = self.db.save_analysis(
            EmailRequest(subject="Meeting", body="Can we meet?"), analysis
        )
        action = next(row for row in self.db.list_rows("proposed_actions") if row["id"] == action_id)
        self.assertEqual(action["action_type"], "calendar_event")
        self.assertIn("2026-09-18T10:00:00+02:00", action["payload_json"])

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

    def test_completing_work_rejects_its_pending_primary_action(self):
        _, commitment_id, action_id = self.db.save_analysis(
            EmailRequest(subject="Task", body="Please handle"),
            EmailAnalysis(category="task", summary="Task", commitment_title="Handle task",
                          proposed_action="Handle the task"),
        )
        self.db.complete_commitment(commitment_id, "Done")
        action = next(row for row in self.db.list_rows("proposed_actions") if row["id"] == action_id)
        self.assertEqual(action["status"], "rejected")

    def test_reply_draft_can_be_edited_before_execution(self):
        _, _, action_id = self.db.save_analysis(
            EmailRequest(subject="Reply", body="Please reply"),
            EmailAnalysis(category="task", summary="Reply", commitment_title="Reply",
                          proposed_action="Draft reply", suggested_reply="Original"),
        )
        updated = self.db.update_action_payload(
            action_id, {"draft_subject": "Re: Updated", "suggested_reply": "Edited body"},
            {"draft_reply"},
        )
        payload = __import__("json").loads(updated["payload_json"])
        self.assertEqual(payload["draft_subject"], "Re: Updated")
        self.assertEqual(payload["suggested_reply"], "Edited body")

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
        question_context = self.db.operator_question_context("What is the status of CARREFOUR?")

        self.assertEqual(decision["status"], "final")
        self.assertEqual(len(context["emails"]), 2)
        self.assertEqual(len(context["commitments"]), 2)
        self.assertEqual(len(context["decisions"]), 1)
        self.assertIn("decision", {event["type"] for event in timeline["events"]})
        self.assertEqual(question_context["matched_entity_names"], ["Carrefour"])
        self.assertTrue(any(key.startswith("commitments:")
                            for key in question_context["available_evidence_keys"]))

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

    def test_entity_merge_preserves_context_decisions_and_aliases(self):
        self.db.save_analysis(
            EmailRequest(subject="Account", body="Account update"),
            EmailAnalysis(category="information", summary="Account update.",
                          company_or_project="Carrefour"),
        )
        source_email_id, _, _ = self.db.save_analysis(
            EmailRequest(subject="Campaign", body="Campaign update"),
            EmailAnalysis(category="decision", summary="Campaign update.",
                          company_or_project="Carrefour campaign",
                          commitment_title="Approve campaign",
                          proposed_action="Review campaign."),
        )
        target = self.db.get_entity("Carrefour")
        source = self.db.get_entity("Carrefour campaign")
        self.db.add_entity_alias(source["id"], "Carrefour marketing")
        self.db.add_decision(source["id"], RecordDecisionRequest(
            title="Campaign scope", decision="Proceed with phase one.",
            source_email_id=source_email_id,
        ))

        merged = self.db.merge_entities(target["id"], "Carrefour campaign")
        context = self.db.entity_context(target["id"])

        self.assertEqual(merged["entity"]["name"], "Carrefour")
        self.assertEqual(len(self.db.list_entities()), 1)
        self.assertEqual(self.db.get_entity("Carrefour campaign")["id"], target["id"])
        self.assertEqual(self.db.get_entity("Carrefour marketing")["id"], target["id"])
        self.assertEqual(len(context["emails"]), 2)
        self.assertEqual(len(context["commitments"]), 1)
        self.assertEqual(len(context["decisions"]), 1)

    def test_alias_and_merge_conflicts_are_rejected(self):
        for name in ("Alpha", "Beta"):
            self.db.save_analysis(
                EmailRequest(subject=name, body="Update"),
                EmailAnalysis(category="information", summary="Update.", company_or_project=name),
            )
        alpha = self.db.get_entity("Alpha")

        with self.assertRaisesRegex(ValueError, "already belongs"):
            self.db.add_entity_alias(alpha["id"], "Beta")
        with self.assertRaisesRegex(ValueError, "same entity"):
            self.db.merge_entities(alpha["id"], "Alpha")

    def test_operator_plan_requires_one_final_decision(self):
        plan = OperatorPlan(
            goal="Prepare a follow-up",
            summary="Review context and draft a reply.",
            steps=[OperatorPlanStep(
                order=1, action="Draft reply", system="gmail", action_type="draft",
                requires_approval=True,
            )],
        )
        saved = self.db.save_operator_plan(plan)
        approved = self.db.decide_operator_plan(saved["id"], "approved", "Looks good")
        repeated = self.db.decide_operator_plan(saved["id"], "rejected", "Too late")

        self.assertEqual(approved["status"], "approved")
        self.assertIsNone(repeated)


if __name__ == "__main__":
    unittest.main()
