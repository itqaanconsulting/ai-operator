import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import main
from database import Database
from models import DecisionRequest, EmailAnalysis, EmailRequest, EmailWorkItem


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


if __name__ == "__main__":
    unittest.main()
