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
from models import DocumentAnalysis


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


if __name__ == "__main__":
    unittest.main()
