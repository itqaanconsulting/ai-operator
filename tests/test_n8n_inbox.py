import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException

import main
from database import Database
from models import GmailImportRequest


class N8nInboxTest(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.original_database = main.database
        main.database = Database(str(Path(self.tempdir.name) / "test.db"))
        main.database.init()

    def tearDown(self):
        main.database = self.original_database
        self.tempdir.cleanup()

    @patch("main._n8n_shared_secret", return_value="test-secret")
    def test_rejects_invalid_secret(self, _secret):
        with self.assertRaises(HTTPException) as raised:
            main.run_n8n_inbox_automation(
                GmailImportRequest(), x_ai_operator_secret="wrong-secret"
            )
        self.assertEqual(raised.exception.status_code, 401)

    @patch("main._execute_inbox_automation")
    @patch("main._n8n_shared_secret", return_value="test-secret")
    def test_returns_review_signal_without_external_action(self, _secret, execute):
        execute.return_value = {
            "processed": [{"action_id": 10}], "skipped": [], "errors": [],
            "follow_up_monitor": {"created": []},
            "open_loop_monitor": {"created": []},
            "document_automation": {"review_ready": []},
        }

        result = main.run_n8n_inbox_automation(
            GmailImportRequest(), x_ai_operator_secret="test-secret"
        )

        self.assertEqual(result["new_work_count"], 1)
        self.assertTrue(result["requires_human_review"])
        self.assertFalse(result["external_action_taken"])
        execute.assert_called_once_with("AI-Operator", 50, "n8n")


if __name__ == "__main__":
    unittest.main()
