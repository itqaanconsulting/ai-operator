import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

import main
from database import Database
from follow_ups import FollowUpMonitor
from models import (
    DecisionRequest,
    EmailAnalysis,
    EmailRequest,
    EmailWorkItem,
    FollowUpProposalUpdateRequest,
)


class FollowUpAutomationTest(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.original_database = main.database
        main.database = Database(str(Path(self.tempdir.name) / "test.db"))
        main.database.init()

    def tearDown(self):
        main.database = self.original_database
        self.tempdir.cleanup()

    def create_follow_up(self):
        return main.database.save_analysis(
            EmailRequest(subject="Pilot proposal", body="Please follow up next week.",
                         gmail_msg_id="gmail-follow-up-1"),
            EmailAnalysis(
                category="follow_up", scenario="sales", summary="Sales follow-up needed.",
                company_or_project="Atlas",
                work_items=[EmailWorkItem(
                    kind="follow_up", title="Follow up on pilot proposal",
                    deadline="2026-09-10T09:00:00+02:00",
                    proposed_action="Schedule a follow-up email.",
                    suggested_reply="Hi, are you ready to discuss the pilot?",
                )],
            ),
        )

    def test_due_follow_up_becomes_approval_gated_gmail_draft(self):
        _, _, action_id = self.create_follow_up()
        action = main.database.list_rows("proposed_actions")[0]
        self.assertEqual(action["action_type"], "schedule_follow_up")

        main.update_follow_up_proposal(action_id, FollowUpProposalUpdateRequest(
            follow_up_at="2026-09-10T09:00:00+02:00", subject="Re: Pilot proposal",
            body="Hi, are you ready to discuss the pilot?",
        ))
        main.approve_action(action_id, DecisionRequest(note="Schedule approved"))
        finished = main.execute_action(action_id)
        self.assertEqual(finished["status"], "executed")

        result = FollowUpMonitor(main.database).run(
            datetime(2026, 9, 10, 8, 0, tzinfo=timezone.utc)
        )
        self.assertEqual(len(result["created"]), 1)
        generated = next(row for row in main.database.list_rows("proposed_actions")
                         if row["id"] == result["created"][0]["action_id"])
        payload = json.loads(generated["payload_json"])
        self.assertEqual(generated["action_type"], "draft_reply")
        self.assertEqual(generated["status"], "pending_approval")
        self.assertEqual(payload["draft_subject"], "Re: Pilot proposal")

        repeated = FollowUpMonitor(main.database).run(
            datetime(2026, 9, 11, tzinfo=timezone.utc)
        )
        self.assertEqual(repeated["created"], [])

    def test_completing_commitment_cancels_scheduled_follow_up(self):
        _, commitment_id, action_id = self.create_follow_up()
        main.approve_action(action_id, DecisionRequest(note="Approved"))
        main.execute_action(action_id)
        main.database.complete_commitment(commitment_id, "Customer replied")

        result = FollowUpMonitor(main.database).run(
            datetime(2026, 9, 11, tzinfo=timezone.utc)
        )
        self.assertEqual(result["created"], [])


if __name__ == "__main__":
    unittest.main()
