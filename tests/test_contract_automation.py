import tempfile
import unittest
from pathlib import Path

from contract_automation import ContractIntakeAutomation
from database import Database
from models import DocumentAnalysis, DocumentComparison


class FakeAnalyzer:
    def analyze_document(self, filename, text):
        return DocumentAnalysis(
            document_type="contract", summary="New Carrefour contract.",
            company_or_project="Carrefour", recommendation="review",
            recommendation_reason="Compare with the approved baseline.",
        )

    def compare_documents(self, candidate_filename, candidate_text,
                          reference_filename, reference_text):
        return DocumentComparison(
            company_or_project="Carrefour",
            executive_summary="The notice period changed.",
            recommendation="revise",
            recommendation_reason="Restore the approved notice period.",
            confidence=0.9,
        )


class ContractIntakeAutomationTest(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.db = Database(str(Path(self.tempdir.name) / "test.db"))
        self.db.init()
        reference_analysis = DocumentAnalysis(
            document_type="contract", summary="Approved Carrefour contract.",
            company_or_project="Carrefour", recommendation="review",
            recommendation_reason="Approved baseline.",
        )
        reference, _, _ = self.db.save_document(
            "approved.txt", "text/plain", "approved-hash",
            "Approved thirty-day notice period.", reference_analysis,
        )
        self.db.add_trusted_reference(
            reference["id"], "Approved Carrefour baseline", "Human reviewed baseline."
        )

    def tearDown(self):
        self.tempdir.cleanup()

    def test_labeled_attachment_is_prepared_for_human_review(self):
        attachment = {
            "gmail_msg_id": "gmail-contract-1", "attachment_id": "attachment-1",
            "filename": "candidate.txt", "mime_type": "text/plain",
            "subject": "New agreement", "sender": "contracts@example.com",
            "data": b"Proposed ninety-day notice period.",
        }
        automation = ContractIntakeAutomation(self.db, FakeAnalyzer())

        first = automation.run([attachment])
        repeated = automation.run([attachment])

        self.assertEqual(len(first["review_ready"]), 1)
        self.assertEqual(first["review_ready"][0]["reference_label"],
                         "Approved Carrefour baseline")
        self.assertTrue(first["human_review_required"])
        self.assertEqual(len(repeated["skipped"]), 1)
        self.assertEqual(repeated["skipped"][0]["reason"], "already_imported")

    def test_document_without_reference_stops_before_comparison(self):
        attachment = {
            "gmail_msg_id": "gmail-report-1", "attachment_id": "attachment-2",
            "filename": "candidate.txt", "mime_type": "text/plain",
            "subject": "Report", "sender": "reports@example.com",
            "data": b"A unique new candidate document.",
        }
        analyzer = FakeAnalyzer()
        original = analyzer.analyze_document
        analyzer.analyze_document = lambda filename, text: DocumentAnalysis(
            document_type="report", summary="A report.", company_or_project="Carrefour",
            recommendation="review", recommendation_reason="Human review required.",
        )

        result = ContractIntakeAutomation(self.db, analyzer).run([attachment])

        self.assertEqual(len(result["analyzed_only"]), 1)
        self.assertEqual(result["analyzed_only"][0]["next_step"],
                         "Assign a trusted reference")
        analyzer.analyze_document = original

    def test_schedule_is_opt_in_and_due_runs_are_claimed_once(self):
        initial = self.db.get_contract_schedule()
        self.assertEqual(initial["enabled"], 0)

        configured = self.db.configure_contract_schedule(True, 15, "AI-Operator", 10)
        claimed = self.db.claim_due_contract_schedule()
        duplicate_claim = self.db.claim_due_contract_schedule()
        self.db.finish_contract_schedule(result={"review_ready": []})
        finished = self.db.get_contract_schedule()

        self.assertEqual(configured["enabled"], 1)
        self.assertIsNotNone(claimed)
        self.assertIsNone(duplicate_claim)
        self.assertEqual(finished["last_status"], "completed")


if __name__ == "__main__":
    unittest.main()
