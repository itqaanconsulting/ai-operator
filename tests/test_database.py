import tempfile
import unittest
from pathlib import Path

from database import Database
from models import ActionStatus, EmailAnalysis, EmailRequest


class DatabaseTest(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.db = Database(str(Path(self.tempdir.name) / "test.db"))
        self.db.init()

    def tearDown(self):
        self.tempdir.cleanup()

    def test_analysis_creates_commitment_and_pending_action(self):
        request = EmailRequest(
            subject="Graag vrijdag bevestigen",
            body="Kun je vrijdag bevestigen of we doorgaan?",
            sender="jan@example.com",
            gmail_msg_id="gmail-1",
        )
        analysis = EmailAnalysis(
            category="decision",
            summary="Jan vraagt om een besluit.",
            contact_name="Jan",
            company_or_project="Project X",
            commitment_title="Besluit over Project X geven",
            deadline="2026-09-04",
            urgency="high",
            proposed_action="Controleer het voorstel en reageer op Jan.",
            suggested_reply="Hoi Jan, ik kom hier vrijdag op terug.",
            confidence=0.94,
        )

        email_id, commitment_id, action_id = self.db.save_analysis(request, analysis)

        self.assertIsNotNone(email_id)
        self.assertIsNotNone(commitment_id)
        self.assertIsNotNone(action_id)
        actions = self.db.list_rows("proposed_actions", "pending_approval")
        self.assertEqual(len(actions), 1)
        self.assertEqual(actions[0]["action_type"], "draft_reply")

    def test_action_can_only_be_decided_once(self):
        request = EmailRequest(subject="Actie", body="Kun je dit bekijken?")
        analysis = EmailAnalysis(
            category="task",
            summary="Verzoek om controle.",
            commitment_title="Verzoek bekijken",
            proposed_action="Bekijk het verzoek.",
        )
        _, _, action_id = self.db.save_analysis(request, analysis)

        approved = self.db.decide_action(action_id, ActionStatus.APPROVED, "Akkoord")
        repeated = self.db.decide_action(action_id, ActionStatus.REJECTED, None)

        self.assertEqual(approved["status"], "approved")
        self.assertIsNone(repeated)

    def test_approved_action_can_only_be_claimed_once(self):
        request = EmailRequest(
            subject="Antwoord nodig", body="Kun je antwoorden?",
            sender="jan@example.com", gmail_msg_id="gmail-2"
        )
        analysis = EmailAnalysis(
            category="task", summary="Antwoord gevraagd.",
            commitment_title="Jan antwoorden", proposed_action="Maak een antwoordconcept.",
            suggested_reply="Hoi Jan, akkoord."
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


if __name__ == "__main__":
    unittest.main()
