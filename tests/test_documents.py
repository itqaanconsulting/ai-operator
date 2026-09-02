import hashlib
import json
import tempfile
import unittest
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace

from docx import Document
from pypdf import PdfWriter

from analyzer import EmailAnalyzer
from database import Database
from document_processor import extract_document
from models import DocumentAnalysis, RevisionRequestDraft


class FakeCompletions:
    def create(self, **kwargs):
        content = json.dumps({
            "document_type": "contract",
            "summary": "A one-year services agreement.",
            "company_or_project": "Carrefour",
            "parties": ["Carrefour", "Supplier"],
            "obligations": ["Supplier provides monthly reports."],
            "deadlines": ["Term ends 2027-09-01."],
            "financial_terms": ["Fee is EUR 1,000 per month."],
            "risk_indicators": ["Termination notice period is unclear."],
            "missing_information": ["Governing law."],
            "recommendation": "revise",
            "recommendation_reason": "Clarify termination and governing law.",
            "confidence": 0.91,
        })
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content))])


class FakeComparisonCompletions:
    def create(self, **kwargs):
        content = json.dumps({
            "company_or_project": "Carrefour",
            "executive_summary": "The candidate changes termination and payment terms.",
            "material_differences": [{
                "topic": "Termination",
                "reference_position": "Thirty days notice.",
                "candidate_position": "Ninety days notice.",
                "significance": "high",
                "impact": "The exit period is three times longer.",
                "suggested_resolution": "Restore the thirty-day notice period."
            }],
            "added_terms": ["Automatic renewal."],
            "removed_terms": ["Liability cap."],
            "unchanged_key_terms": ["One-year initial term."],
            "missing_information": [],
            "recommendation": "revise",
            "recommendation_reason": "Resolve the high-impact deviations.",
            "confidence": 0.9,
        })
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content))])


class FakeRevisionDraftCompletions:
    def create(self, **kwargs):
        content = json.dumps({
            "subject": "Requested revisions to the proposed agreement",
            "body": "Please revise the termination notice period before we continue our review.",
            "requested_changes": ["Restore the thirty-day termination notice period."],
        })
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content))])


class DocumentTest(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.db = Database(str(Path(self.tempdir.name) / "test.db"))
        self.db.init()

    def tearDown(self):
        self.tempdir.cleanup()

    def test_extracts_txt_and_docx(self):
        raw = b"Carrefour services agreement"
        text, digest = extract_document("agreement.txt", raw)
        self.assertEqual(text, raw.decode())
        self.assertEqual(digest, hashlib.sha256(raw).hexdigest())

        document = Document()
        document.add_paragraph("Monthly reporting obligation")
        buffer = BytesIO()
        document.save(buffer)
        text, _ = extract_document("agreement.docx", buffer.getvalue())
        self.assertIn("Monthly reporting", text)

    def test_blank_pdf_explains_ocr_limitation(self):
        writer = PdfWriter()
        writer.add_blank_page(width=100, height=100)
        buffer = BytesIO()
        writer.write(buffer)
        with self.assertRaisesRegex(ValueError, "OCR"):
            extract_document("scan.pdf", buffer.getvalue())

    def test_ai_analysis_is_stored_linked_and_deduplicated(self):
        client = SimpleNamespace(chat=SimpleNamespace(completions=FakeCompletions()))
        analysis = EmailAnalyzer(client=client, model="test").analyze_document(
            "agreement.txt", "Services agreement"
        )
        first, entity_id, duplicate = self.db.save_document(
            "agreement.txt", "text/plain", "same-hash", "Services agreement", analysis
        )
        second, second_entity_id, second_duplicate = self.db.save_document(
            "renamed.txt", "text/plain", "same-hash", "Services agreement", analysis
        )

        self.assertEqual(analysis.recommendation, "revise")
        self.assertFalse(duplicate)
        self.assertTrue(second_duplicate)
        self.assertEqual(first["id"], second["id"])
        self.assertEqual(entity_id, second_entity_id)
        context = self.db.entity_context(entity_id)
        self.assertEqual(len(context["documents"]), 1)
        self.assertIn("document", {event["type"] for event in self.db.entity_timeline(entity_id)["events"]})

    def test_comparison_is_structured_linked_and_deduplicated(self):
        client = SimpleNamespace(chat=SimpleNamespace(completions=FakeComparisonCompletions()))
        comparison = EmailAnalyzer(client=client, model="test").compare_documents(
            "candidate.txt", "Ninety days notice.",
            "reference.txt", "Thirty days notice.",
        )
        first, entity_id, duplicate = self.db.save_document_comparison(
            "candidate.txt", "candidate-hash", "reference.txt", "reference-hash", comparison
        )
        second, _, second_duplicate = self.db.save_document_comparison(
            "renamed.txt", "candidate-hash", "reference.txt", "reference-hash", comparison
        )

        self.assertEqual(comparison.material_differences[0].significance, "high")
        self.assertFalse(duplicate)
        self.assertTrue(second_duplicate)
        self.assertEqual(first["id"], second["id"])
        context = self.db.entity_context(entity_id)
        self.assertEqual(len(context["document_comparisons"]), 1)
        self.assertIn(
            "document_comparison",
            {event["type"] for event in self.db.entity_timeline(entity_id)["events"]},
        )

    def test_ai_confidence_labels_are_normalized(self):
        payload = {
            "executive_summary": "No material differences found.",
            "recommendation": "review",
            "recommendation_reason": "Human confirmation remains required.",
            "confidence": "high",
        }

        from models import DocumentComparison
        comparison = DocumentComparison.model_validate(payload)

        self.assertEqual(comparison.confidence, 0.85)

    def test_comparison_human_decision_is_final_and_auditable(self):
        client = SimpleNamespace(chat=SimpleNamespace(completions=FakeComparisonCompletions()))
        comparison = EmailAnalyzer(client=client, model="test").compare_documents(
            "candidate.txt", "Ninety days notice.", "reference.txt", "Thirty days notice."
        )
        stored, _, _ = self.db.save_document_comparison(
            "candidate.txt", "candidate-decision-hash",
            "reference.txt", "reference-decision-hash", comparison,
        )

        review, error = self.db.decide_document_comparison(
            stored["id"], "revision_requested", "Restore the approved notice period."
        )
        repeated, repeated_error = self.db.decide_document_comparison(
            stored["id"], "approved", "Changed my mind."
        )

        self.assertIsNone(error)
        self.assertEqual(review["decision"], "revision_requested")
        self.assertIsNone(repeated)
        self.assertEqual(repeated_error, "already_decided")
        listed = next(item for item in self.db.list_document_comparisons()
                      if item["id"] == stored["id"])
        self.assertEqual(listed["review_status"], "revision_requested")

    def test_revision_draft_uses_human_decision_and_is_deduplicated(self):
        comparison_client = SimpleNamespace(
            chat=SimpleNamespace(completions=FakeComparisonCompletions())
        )
        comparison = EmailAnalyzer(client=comparison_client, model="test").compare_documents(
            "candidate.txt", "Ninety days notice.", "reference.txt", "Thirty days notice."
        )
        stored, _, _ = self.db.save_document_comparison(
            "candidate.txt", "candidate-draft-hash",
            "reference.txt", "reference-draft-hash", comparison,
        )
        self.db.decide_document_comparison(
            stored["id"], "revision_requested", "Restore the approved notice period."
        )
        context = self.db.get_revision_draft_context(stored["id"])
        draft_client = SimpleNamespace(chat=SimpleNamespace(completions=FakeRevisionDraftCompletions()))
        draft = EmailAnalyzer(client=draft_client, model="test").create_revision_request_draft(
            json.loads(context["comparison_json"]), context["note"]
        )

        first, duplicate = self.db.save_revision_draft(stored["id"], draft)
        second, second_duplicate = self.db.save_revision_draft(stored["id"], draft)

        self.assertFalse(duplicate)
        self.assertTrue(second_duplicate)
        self.assertEqual(first["id"], second["id"])
        self.assertIn("termination", first["body"])
        self.assertEqual(self.db.get_revision_draft_context(stored["id"])["draft_id"], first["id"])

        delivery, error = self.db.approve_revision_draft_delivery(
            first["id"], "contracts@example.com", "Recipient and wording verified."
        )
        repeated, repeated_error = self.db.approve_revision_draft_delivery(
            first["id"], "other@example.com", "Try changing recipient."
        )
        claimed = self.db.claim_revision_draft_delivery(delivery["id"])
        duplicate_claim = self.db.claim_revision_draft_delivery(delivery["id"])
        finished = self.db.finish_revision_draft_delivery(delivery["id"], "gmail-draft-1")

        self.assertIsNone(error)
        self.assertEqual(delivery["status"], "approved")
        self.assertIsNone(repeated)
        self.assertEqual(repeated_error, "already_approved")
        self.assertEqual(claimed["recipient"], "contracts@example.com")
        self.assertIsNone(duplicate_claim)
        self.assertEqual(finished["status"], "executed")
        self.assertEqual(finished["provider_draft_id"], "gmail-draft-1")


if __name__ == "__main__":
    unittest.main()
