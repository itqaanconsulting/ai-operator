import tempfile
import unittest
import os
import json
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

    @patch("main._n8n_shared_secret", return_value="test-secret")
    def test_hired_trello_card_prepares_onboarding_review(self, _secret):
        _, _, action_id = main.database.save_analysis(
            EmailRequest(
                sender="Sam <sam@example.com>", subject="Application for Engineer",
                body="Sam applied.",
            ),
            EmailAnalysis(
                category="task", scenario="hr", summary="Sam applied.", contact_name="Sam",
                work_items=[EmailWorkItem(kind="job_application", title="Review Sam for Engineer",
                                          proposed_action="Create candidate review.")],
            ),
        )
        main.approve_action(action_id, DecisionRequest(note="Approved"))
        main.execute_action(action_id)
        record = main.database.list_operational_records()[0]
        dispatch, _ = main.database.claim_integration_dispatch(record["id"], "trello")
        main.database.finish_integration_dispatch(dispatch["id"], {"id": "card-hired-1"})

        result = main.receive_trello_candidate_status(
            TrelloCandidateStatusRequest(
                card_id="card-hired-1", list_name="Hired", event_id="poll-hired-1"
            ),
            "test-secret",
        )

        action = main.database.get_action_context(result["action_id"])
        self.assertEqual(result["decision"], "hire")
        self.assertTrue(result["requires_human_review"])
        self.assertEqual(action["action_type"], "create_onboarding_package")
        self.assertEqual(action["status"], "pending_approval")

    def test_candidate_result_template_keeps_hired_cards_in_hired_list(self):
        workflow = json.loads(
            Path("n8n/candidate-result-to-trello.json").read_text(encoding="utf-8")
        )
        update_card = next(
            node for node in workflow["nodes"] if node["name"] == "Move card to final status"
        )
        list_mapping = update_card["parameters"]["updateFields"]["idList"]

        self.assertIn("status === 'hired'", list_mapping)
        self.assertIn("REPLACE_WITH_HIRED_LIST_ID", list_mapping)

    @patch("main.dispatch_employee_to_hris")
    def test_approved_onboarding_syncs_to_airtable_once(self, dispatch_hris):
        dispatch_hris.return_value = {"id": "recEmployee1"}
        _, _, action_id = main.database.save_analysis(
            EmailRequest(
                sender="Amina <amina@example.com>", subject="Application for Engineer",
                body="Amina applied.",
            ),
            EmailAnalysis(
                category="task", scenario="hr", summary="Amina applied.", contact_name="Amina",
                work_items=[EmailWorkItem(
                    kind="job_application", title="Review Amina for Engineer",
                    proposed_action="Create candidate review.",
                )],
            ),
        )
        main.approve_action(action_id, DecisionRequest(note="Approved"))
        main.execute_action(action_id)
        record = main.database.list_operational_records()[0]
        prepared = main.database.prepare_candidate_review_action(record["id"], "hire")
        from models import CandidateOnboardingPackageUpdateRequest
        main.update_candidate_onboarding_package(
            prepared["action_id"], CandidateOnboardingPackageUpdateRequest(
                employee_name="Amina", personal_email="amina@example.com",
                job_title="Engineer", start_date="2030-10-01",
                employment_type="permanent", legal_entity="Example B.V.",
                hours_per_week=40,
            ),
        )

        with patch.dict(os.environ, {
            "N8N_AIRTABLE_HRIS_WEBHOOK_URL": "http://n8n.test/airtable",
            "N8N_SHARED_SECRET": "test-secret",
        }):
            main.approve_action(prepared["action_id"], DecisionRequest(note="HR approved"))
            result = main.execute_action(prepared["action_id"])
            package_id = json.loads(result["payload_json"])["external_result"][
                "onboarding_package_id"
            ]
            second = main.sync_onboarding_package_to_hris(package_id)

        self.assertEqual(result["hris"]["status"], "completed")
        self.assertTrue(second["duplicate"])
        self.assertEqual(dispatch_hris.call_count, 1)
        stored = main.database.list_operational_records()[0]
        self.assertEqual(stored["hris_status"], "completed")
        self.assertEqual(stored["hris_employee_id"], "recEmployee1")
        payload = dispatch_hris.call_args.args[2]
        self.assertEqual(payload["employment_type"], "Permanent")
        self.assertEqual(payload["contract_status"], "Draft")

    def test_airtable_workflow_targets_created_employee_table(self):
        workflow = json.loads(
            Path("n8n/airtable-employee-onboarding.json").read_text(encoding="utf-8")
        )
        node = next(node for node in workflow["nodes"] if node["name"] == "Create Airtable employee")

        self.assertIn("REPLACE_WITH_AIRTABLE_BASE_ID", node["parameters"]["url"])
        self.assertIn("REPLACE_WITH_EMPLOYEES_TABLE_ID", node["parameters"]["url"])
        self.assertIn("Employee ID", node["parameters"]["body"])


if __name__ == "__main__":
    unittest.main()
