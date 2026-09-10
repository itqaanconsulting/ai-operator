import tempfile
import unittest
import os
from pathlib import Path
from unittest.mock import patch

import main
from database import Database
from models import (
    DecisionRequest, EmailAnalysis, EmailRequest, EmailWorkItem,
    TrelloCandidateStatusRequest,
)


class N8nIntegrationTest(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.original_database = main.database
        main.database = Database(str(Path(self.tempdir.name) / "test.db"))
        main.database.init()

    def tearDown(self):
        main.database = self.original_database
        self.tempdir.cleanup()

    def create_record(self):
        _, _, action_id = main.database.save_analysis(
            EmailRequest(subject="New lead", body="A retailer wants a pilot."),
            EmailAnalysis(
                category="task", scenario="sales", summary="Qualified lead.",
                company_or_project="Carrefour",
                work_items=[EmailWorkItem(
                    kind="sales_lead", title="Carrefour pilot lead",
                    proposed_action="Schedule a discovery call.", owner="Sales",
                )],
            ),
        )
        main.approve_action(action_id, DecisionRequest(note="Approved"))
        main.execute_action(action_id)
        return main.database.list_operational_records()[0]

    @patch("main.dispatch_operational_record")
    def test_approved_record_is_sent_once(self, dispatch):
        record = self.create_record()
        dispatch.return_value = {
            "id": "card-1", "url": "https://trello.com/c/card-1", "name": record["title"],
        }

        first = main.send_operational_record_to_trello(record["id"])
        second = main.send_operational_record_to_trello(record["id"])

        self.assertFalse(first["duplicate"])
        self.assertTrue(second["duplicate"])
        self.assertEqual(dispatch.call_count, 1)
        stored = main.database.list_operational_records()[0]
        self.assertEqual(stored["trello_status"], "completed")
        self.assertEqual(stored["trello_card_url"], "https://trello.com/c/card-1")

    @patch("main.dispatch_operational_record")
    def test_failed_dispatch_can_be_retried(self, dispatch):
        record = self.create_record()
        from n8n_operator import N8nDispatchError
        dispatch.side_effect = N8nDispatchError("n8n unavailable")
        with self.assertRaises(Exception):
            main.send_operational_record_to_trello(record["id"])
        self.assertEqual(main.database.list_operational_records()[0]["trello_status"], "failed")

        dispatch.side_effect = None
        dispatch.return_value = {"id": "card-2", "shortUrl": "https://trello.com/c/card-2"}
        retried = main.send_operational_record_to_trello(record["id"])
        self.assertFalse(retried["duplicate"])
        self.assertEqual(dispatch.call_count, 2)

    @patch.dict(os.environ, {"N8N_TRELLO_WEBHOOK_URL": "http://n8n.test/candidate"})
    @patch("main.dispatch_operational_record")
    def test_approved_candidate_is_automatically_sent_to_hiring_board(self, dispatch):
        dispatch.return_value = {
            "id": "candidate-card-1", "shortUrl": "https://trello.com/c/candidate-card-1",
        }
        _, _, action_id = main.database.save_analysis(
            EmailRequest(subject="Application", body="Sarah applied."),
            EmailAnalysis(
                category="task", scenario="hr", summary="Sarah applied.",
                work_items=[EmailWorkItem(
                    kind="job_application", title="Review Sarah",
                    proposed_action="Create candidate review.",
                )],
            ),
        )

        main.approve_action(action_id, DecisionRequest(note="Approved"))
        executed = main.execute_action(action_id)

        record = main.database.list_operational_records()[0]
        self.assertEqual(executed["status"], "executed")
        self.assertEqual(record["trello_status"], "completed")
        self.assertEqual(record["trello_card_id"], "candidate-card-1")
        self.assertEqual(dispatch.call_count, 1)

    @patch("main._n8n_shared_secret", return_value="test-secret")
    def test_repeated_trello_candidate_poll_is_idempotent(self, _secret):
        _, _, action_id = main.database.save_analysis(
            EmailRequest(subject="Application", body="Sam applied."),
            EmailAnalysis(
                category="task", scenario="hr", summary="Sam applied.", contact_name="Sam",
                work_items=[EmailWorkItem(kind="job_application", title="Review Sam",
                                          proposed_action="Create candidate review.")],
            ),
        )
        main.approve_action(action_id, DecisionRequest(note="Approved"))
        main.execute_action(action_id)
        record = main.database.list_operational_records()[0]
        dispatch, _ = main.database.claim_integration_dispatch(record["id"], "trello")
        main.database.finish_integration_dispatch(dispatch["id"], {"id": "card-hr-1"})
        request = TrelloCandidateStatusRequest(
            card_id="card-hr-1", list_name="Schedule interview", event_id="poll-1"
        )

        first = main.receive_trello_candidate_status(request, "test-secret")
        second = main.receive_trello_candidate_status(request, "test-secret")

        self.assertFalse(first["duplicate"])
        self.assertTrue(second["duplicate"])
        packages = [row for row in main.database.list_rows("proposed_actions")
                    if row["action_type"] == "candidate_interview_package"]
        self.assertEqual(len(packages), 1)


if __name__ == "__main__":
    unittest.main()
