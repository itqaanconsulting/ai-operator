import json
import tempfile
import unittest
from pathlib import Path

import main
from database import Database
from models import (
    ActionStatus, CalendarEventProposalUpdateRequest, CandidateInterviewPackageUpdateRequest,
    CandidateOnboardingPackageUpdateRequest,
    DecisionRequest, EmailAnalysis, EmailRequest, EmailWorkItem,
)
from unittest.mock import patch


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
            "job_application": "candidate_review", "risk": "escalation",
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

    def test_candidate_review_prepares_interview_for_review_inbox(self):
        _, commitment_id, action_id = main.database.save_analysis(
            EmailRequest(subject="Application for Engineer", body="Sam applied."),
            EmailAnalysis(
                category="task", scenario="hr", summary="Sam applied.", contact_name="Sam",
                work_items=[EmailWorkItem(
                    kind="job_application", title="Review Sam for Engineer",
                    proposed_action="Create a candidate review.", owner="Recruiting",
                )],
            ),
        )
        main.approve_action(action_id, DecisionRequest(note="Approved"))
        main.execute_action(action_id)
        record = main.database.list_operational_records()[0]

        prepared = main.database.prepare_candidate_review_action(record["id"], "interview")
        next_action = next(row for row in main.database.list_rows("proposed_actions")
                           if row["id"] == prepared["action_id"])
        commitment = next(row for row in main.database.list_rows("commitments")
                          if row["id"] == commitment_id)

        self.assertEqual(prepared["status"], "interview_pending")
        self.assertEqual(next_action["action_type"], "candidate_interview_package")
        self.assertIn('"candidate_review_id"', next_action["payload_json"])
        self.assertIn('"suggested_reply"', next_action["payload_json"])
        self.assertIn('"attendees": [', next_action["payload_json"])
        self.assertEqual(commitment["status"], "open")

    def test_candidate_follow_up_survives_database_restart_after_intake_is_complete(self):
        _, commitment_id, action_id = main.database.save_analysis(
            EmailRequest(subject="Application for Engineer", body="Amina applied."),
            EmailAnalysis(
                category="task", scenario="hr", summary="Amina applied.", contact_name="Amina",
                work_items=[EmailWorkItem(
                    kind="job_application", title="Review Amina for Engineer",
                    proposed_action="Create a candidate review.", owner="Recruiting",
                )],
            ),
        )
        main.approve_action(action_id, DecisionRequest(note="Approved"))
        main.execute_action(action_id)
        record = main.database.list_operational_records()[0]
        prepared = main.database.prepare_candidate_review_action(record["id"], "interview")

        with main.database.connect() as connection:
            connection.execute(
                "UPDATE commitments SET status = 'completed' WHERE id = ?", (commitment_id,)
            )
        restarted_database = Database(main.database.path)
        restarted_database.init()
        follow_up = next(
            row for row in restarted_database.list_rows("proposed_actions")
            if row["id"] == prepared["action_id"]
        )

        self.assertEqual(follow_up["status"], ActionStatus.PENDING_APPROVAL.value)

    def test_candidate_can_remain_under_review_without_external_action(self):
        _, _, action_id = main.database.save_analysis(
            EmailRequest(subject="Application", body="Candidate applied."),
            EmailAnalysis(
                category="task", scenario="hr", summary="Candidate applied.",
                work_items=[EmailWorkItem(
                    kind="job_application", title="Review candidate",
                    proposed_action="Create a candidate review.",
                )],
            ),
        )
        main.approve_action(action_id, DecisionRequest(note="Approved"))
        main.execute_action(action_id)
        record = main.database.list_operational_records()[0]

        result = main.database.prepare_candidate_review_action(record["id"], "hold")

        self.assertEqual(result["status"], "on_hold")
        self.assertIsNone(result["action_id"])

    def test_hired_candidate_creates_employee_record_and_draft_contract(self):
        _, _, action_id = main.database.save_analysis(
            EmailRequest(
                sender="Amina Yusuf <amina@example.com>",
                subject="Application for Automation Engineer",
                body="Amina applied.",
            ),
            EmailAnalysis(
                category="task", scenario="hr", summary="Amina applied.", contact_name="Amina Yusuf",
                work_items=[EmailWorkItem(
                    kind="job_application", title="Review Amina Yusuf for Automation Engineer",
                    proposed_action="Create a candidate review.", owner="Recruiting",
                )],
            ),
        )
        main.approve_action(action_id, DecisionRequest(note="Approved"))
        main.execute_action(action_id)
        record = main.database.list_operational_records()[0]
        prepared = main.database.prepare_candidate_review_action(record["id"], "hire")
        onboarding = CandidateOnboardingPackageUpdateRequest(
            employee_name="Amina Yusuf", personal_email="amina@example.com",
            job_title="Automation Engineer", start_date="2030-10-01",
            employment_type="permanent", legal_entity="Example Operations B.V.",
            manager="Hiring Manager", work_location="Amsterdam", hours_per_week=40,
        )

        main.update_candidate_onboarding_package(
            prepared["action_id"], onboarding,
        )
        original_action = main.database.get_action_context(prepared["action_id"])
        duplicate_payload = json.dumps({
            "candidate_review_id": record["id"], "onboarding": onboarding.model_dump()
        })
        with main.database.connect() as connection:
            duplicate_action_id = connection.execute(
                """INSERT INTO proposed_actions
                   (commitment_id, email_id, action_type, description, payload_json, status)
                   VALUES (?, ?, 'create_onboarding_package', 'Retry onboarding', ?, 'pending_approval')""",
                (original_action["commitment_id"], original_action["email_id"], duplicate_payload),
            ).lastrowid
        main.approve_action(prepared["action_id"], DecisionRequest(note="HR reviewed"))
        result = main.execute_action(prepared["action_id"])
        updated = main.database.get_operational_record(record["id"])
        package_id = json.loads(result["payload_json"])["external_result"]["onboarding_package_id"]
        package = main.database.get_onboarding_package(package_id)

        self.assertEqual(updated["status"], "hired")
        self.assertEqual(package["status"], "draft")
        self.assertIn("DRAFT — FOR HR AND LEGAL REVIEW ONLY", package["contract_draft"])
        self.assertIn("Example Operations B.V.", package["contract_draft"])
        self.assertIn("1. PARTIES", package["contract_draft"])
        self.assertIn("4. TERMS TO BE COMPLETED BY HR AND LEGAL", package["contract_draft"])

        duplicate_action = main.database.get_action_context(duplicate_action_id)
        self.assertEqual(duplicate_action["status"], "rejected")
        recovered = main.database.create_onboarding_package(
            duplicate_action, onboarding.model_dump(), main.build_contract_draft(onboarding)
        )

        self.assertTrue(recovered["duplicate"])
        self.assertEqual(recovered["id"], package_id)
        with main.database.connect() as connection:
            package_count = connection.execute(
                "SELECT COUNT(*) AS count FROM onboarding_packages"
            ).fetchone()["count"]
        self.assertEqual(package_count, 1)

    def test_trello_recreates_missing_interview_approval_for_pending_candidate(self):
        _, _, action_id = main.database.save_analysis(
            EmailRequest(subject="Application", body="Candidate applied."),
            EmailAnalysis(
                category="task", scenario="hr", summary="Candidate applied.",
                work_items=[EmailWorkItem(
                    kind="job_application", title="Review candidate",
                    proposed_action="Create a candidate review.",
                )],
            ),
        )
        main.approve_action(action_id, DecisionRequest(note="Approved"))
        main.execute_action(action_id)
        record = main.database.list_operational_records()[0]
        first = main.database.prepare_candidate_review_action(record["id"], "interview")
        main.database.decide_action(first["action_id"], ActionStatus.REJECTED, "Old action closed")

        retried = main.database.prepare_candidate_review_action(record["id"], "interview")

        self.assertFalse(retried["duplicate"])
        self.assertNotEqual(retried["action_id"], first["action_id"])
        self.assertEqual(retried["status"], "interview_pending")

    @patch.dict(main.os.environ, {"SAFE_DEMO_MODE": "false"})
    @patch("main.CalendarOperator.suggest_interview_slots")
    @patch("main.get_calendar_service")
    def test_candidate_interview_slot_endpoint_uses_ai_availability(
        self, _calendar_service, suggest_slots
    ):
        _, _, action_id = main.database.save_analysis(
            EmailRequest(subject="Application", body="Tuesday afternoon works.", gmail_msg_id="gmail-slots"),
            EmailAnalysis(
                category="task", scenario="hr", summary="Sam applied.", contact_name="Sam",
                availability_preferences="Tuesday afternoon",
                work_items=[EmailWorkItem(kind="job_application", title="Review Sam",
                                          proposed_action="Create candidate review.")],
            ),
        )
        main.approve_action(action_id, DecisionRequest(note="Approved"))
        main.execute_action(action_id)
        record = main.database.list_operational_records()[0]
        prepared = main.database.prepare_candidate_review_action(record["id"], "interview")
        suggest_slots.return_value = [{
            "start_at": "2030-09-17T13:00:00+02:00",
            "end_at": "2030-09-17T13:30:00+02:00", "label": "Tue 17 Sep, 13:00",
            "preference_match": True, "reason": "Tuesday afternoon",
        }]

        result = main.suggest_candidate_interview_slots(prepared["action_id"])

        self.assertEqual(len(result["slots"]), 1)
        self.assertIn("Tuesday afternoon", suggest_slots.call_args.kwargs["preference_text"])

    @patch.dict(main.os.environ, {"SAFE_DEMO_MODE": "true"})
    @patch("main.get_calendar_service")
    def test_candidate_interview_slots_are_fictional_in_safe_demo_mode(
        self, calendar_service
    ):
        _, _, action_id = main.database.save_analysis(
            EmailRequest(subject="Application", body="Candidate applied."),
            EmailAnalysis(
                category="task", scenario="hr", summary="Amina applied.", contact_name="Amina",
                work_items=[EmailWorkItem(kind="job_application", title="Review Amina",
                                          proposed_action="Create candidate review.")],
            ),
        )
        main.approve_action(action_id, DecisionRequest(note="Approved"))
        main.execute_action(action_id)
        record = main.database.list_operational_records()[0]
        prepared = main.database.prepare_candidate_review_action(record["id"], "interview")
        main.database.update_action_payload(
            prepared["action_id"],
            {"calendar_event": {
                "title": "Interview - Amina",
                "start_at": "2030-09-17T14:30:00+02:00",
                "end_at": "2030-09-17T15:00:00+02:00",
            }},
            {"candidate_interview_package"},
        )

        result = main.suggest_candidate_interview_slots(prepared["action_id"])

        self.assertEqual(len(result["slots"]), 3)
        self.assertEqual(result["slots"][0]["reason"], "Fictional demo availability")
        calendar_service.assert_not_called()

    @patch("main.CalendarOperator.create_event")
    @patch("main.GmailOperator.create_reply_draft")
    @patch("main.get_calendar_service")
    @patch("main.get_gmail_service")
    def test_candidate_interview_package_creates_calendar_and_gmail_draft(
        self, gmail_service, calendar_service, create_draft, create_event
    ):
        _, _, action_id = main.database.save_analysis(
            EmailRequest(subject="Application", body="Sam applied.", gmail_msg_id="gmail-1"),
            EmailAnalysis(
                category="task", scenario="hr", summary="Sam applied.", contact_name="Sam",
                work_items=[EmailWorkItem(kind="job_application", title="Review Sam",
                                          proposed_action="Create candidate review.")],
            ),
        )
        main.approve_action(action_id, DecisionRequest(note="Approved"))
        main.execute_action(action_id)
        record = main.database.list_operational_records()[0]
        prepared = main.database.prepare_candidate_review_action(record["id"], "interview")
        main.update_candidate_interview_package(
            prepared["action_id"],
            CandidateInterviewPackageUpdateRequest(
                calendar_event=CalendarEventProposalUpdateRequest(
                    title="Interview with Sam", start_at="2030-09-18T10:00:00+02:00",
                    end_at="2030-09-18T10:30:00+02:00", attendees=["sam@example.com"],
                ),
                email_subject="Interview invitation", email_body="Hi Sam, we invite you.",
            ),
        )
        create_draft.return_value = {"provider": "gmail", "draft_id": "draft-1"}
        create_event.return_value = {"provider": "google_calendar", "event_id": "event-1"}

        main.approve_action(prepared["action_id"], DecisionRequest(note="Approved"))
        finished = main.execute_action(prepared["action_id"])

        self.assertEqual(finished["status"], "executed")
        create_draft.assert_called_once()
        create_event.assert_called_once()
        updated = main.database.get_operational_record(record["id"])
        self.assertEqual(updated["status"], "interview_scheduled")


if __name__ == "__main__":
    unittest.main()
