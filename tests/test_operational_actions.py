import tempfile
import unittest
from pathlib import Path

import main
from database import Database
from models import DecisionRequest, EmailAnalysis, EmailRequest, EmailWorkItem


class OperationalActionTest(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.original_database = main.database
        main.database = Database(str(Path(self.tempdir.name) / "test.db"))
        main.database.init()

    def tearDown(self):
        main.database = self.original_database
        self.tempdir.cleanup()

    def test_ai_work_kinds_map_to_business_records(self):
        expected = {
            "task": "task", "sales_lead": "crm_lead", "payment": "finance_review",
            "customer_issue": "support_case", "contract_review": "document_review",
            "risk": "escalation",
        }
        for index, (kind, record_type) in enumerate(expected.items()):
            with self.subTest(kind=kind):
                _, _, action_id = main.database.save_analysis(
                    EmailRequest(subject=f"Scenario {kind}", body="Action required."),
                    EmailAnalysis(
                        category="task", summary="Work detected.", company_or_project="Atlas",
                        work_items=[EmailWorkItem(
                            kind=kind, title=f"Handle {kind}", deadline="2026-09-20",
                            urgency="high", proposed_action=f"Review {kind}.",
                            amount=1250 if kind == "payment" else None,
                            currency="EUR" if kind == "payment" else None,
                        )],
                    ),
                )
                action = next(row for row in main.database.list_rows("proposed_actions")
                              if row["id"] == action_id)
                self.assertEqual(action["action_type"], "create_operational_record")
                self.assertIn(f'"record_type": "{record_type}"', action["payload_json"])

    def test_approved_business_record_is_created_once(self):
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
        finished = main.execute_action(action_id)
        records = main.database.list_operational_records()

        self.assertEqual(finished["status"], "executed")
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["record_type"], "crm_lead")
        self.assertEqual(records[0]["entity_name"], "Carrefour")
        self.assertEqual(records[0]["owner"], "Sales")


if __name__ == "__main__":
    unittest.main()
