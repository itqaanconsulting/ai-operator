import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from calendar_operator import CalendarOperator
from database import Database
from models import CalendarEventProposalUpdateRequest, EmailAnalysis, EmailRequest, EmailWorkItem


class Executable:
    def __init__(self, result):
        self.result = result

    def execute(self):
        return self.result


class EventsResource:
    def __init__(self, items):
        self.items = items
        self.kwargs = None
        self.insert_kwargs = None

    def list(self, **kwargs):
        self.kwargs = kwargs
        return Executable({"items": self.items})

    def insert(self, **kwargs):
        self.insert_kwargs = kwargs
        return Executable({"id": "created-1", "htmlLink": "https://calendar.google.com/created-1"})


class FakeCalendarService:
    def __init__(self, items):
        self.resource = EventsResource(items)

    def events(self):
        return self.resource


class CalendarOperatorTest(unittest.TestCase):
    def test_missing_end_defaults_to_thirty_minutes(self):
        proposal = CalendarEventProposalUpdateRequest(
            title="Future review", start_at="2030-09-18T10:00:00+02:00"
        )
        self.assertEqual(proposal.end_at, "2030-09-18T10:30:00+02:00")

    def test_past_start_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "must be in the future"):
            CalendarEventProposalUpdateRequest(
                title="Old review", start_at="2020-09-18T10:00:00+02:00"
            )

    def test_calendar_events_are_normalized_from_bounded_window(self):
        service = FakeCalendarService([{
            "id": "event-1",
            "summary": "Carrefour campaign review",
            "description": "Review the proposal.",
            "start": {"dateTime": "2026-09-04T10:00:00+02:00"},
            "end": {"dateTime": "2026-09-04T10:30:00+02:00"},
            "attendees": [{"email": "jane@example.com"}],
            "status": "confirmed",
            "htmlLink": "https://calendar.google.com/event-1",
            "updated": "2026-09-02T08:00:00Z",
        }])
        operator = CalendarOperator(service)

        events = operator.list_events(
            days_before=7, days_after=30,
            now=datetime(2026, 9, 2, 12, 0, tzinfo=timezone.utc),
        )

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["google_event_id"], "event-1")
        self.assertEqual(json.loads(events[0]["attendees_json"]), ["jane@example.com"])
        self.assertFalse(events[0]["all_day"])
        self.assertTrue(service.resource.kwargs["singleEvents"])
        self.assertEqual(service.resource.kwargs["orderBy"], "startTime")

    def test_all_day_event_is_supported(self):
        service = FakeCalendarService([{
            "id": "event-2", "summary": "Carrefour deadline",
            "start": {"date": "2026-09-04"}, "end": {"date": "2026-09-05"},
        }])
        event = CalendarOperator(service).list_events()[0]

        self.assertTrue(event["all_day"])
        self.assertEqual(event["start_at"], "2026-09-04")

    def test_create_event_never_sends_attendee_updates(self):
        service = FakeCalendarService([])
        result = CalendarOperator(service).create_event({
            "title": "Carrefour review", "start_at": "2026-09-18T10:00:00+02:00",
            "end_at": "2026-09-18T10:30:00+02:00", "location": "Online",
            "attendees": ["jane@example.com"],
        })
        self.assertEqual(result["event_id"], "created-1")
        self.assertEqual(service.resource.insert_kwargs["sendUpdates"], "none")
        self.assertEqual(service.resource.insert_kwargs["body"]["attendees"][0]["email"], "jane@example.com")

    def test_interview_slots_prefer_requested_days_and_avoid_busy_times(self):
        service = FakeCalendarService([{
            "id": "busy-1", "summary": "Existing meeting",
            "start": {"dateTime": "2026-09-15T13:00:00+02:00"},
            "end": {"dateTime": "2026-09-15T13:30:00+02:00"},
        }])

        slots = CalendarOperator(service).suggest_interview_slots(
            "I am available next week, preferably Tuesday or Wednesday afternoon.",
            now=datetime(2026, 9, 9, 10, 0, tzinfo=timezone.utc),
        )

        self.assertEqual(len(slots), 3)
        self.assertEqual(slots[0]["start_at"], "2026-09-15T13:30:00+02:00")
        self.assertTrue(all(slot["preference_match"] for slot in slots))
        self.assertNotIn("2026-09-15T13:00:00+02:00", {slot["start_at"] for slot in slots})


class CalendarDatabaseTest(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.db = Database(str(Path(self.tempdir.name) / "test.db"))
        self.db.init()
        self.db.save_analysis(
            EmailRequest(subject="Account", body="Carrefour account update"),
            EmailAnalysis(category="information", summary="Account update.",
                          company_or_project="Carrefour"),
        )

    def tearDown(self):
        self.tempdir.cleanup()

    def event(self, title="Carrefour campaign review"):
        return {
            "google_event_id": "event-1", "calendar_id": "primary", "title": title,
            "description": "Review the campaign proposal.", "location": None,
            "start_at": "2026-09-04T10:00:00+02:00",
            "end_at": "2026-09-04T10:30:00+02:00", "all_day": False,
            "status": "confirmed", "attendees_json": "[]", "html_link": None,
            "meeting_link": None, "updated_at_source": "2026-09-02T08:00:00Z",
        }

    def test_event_is_matched_stored_updated_and_added_to_timeline(self):
        matches = self.db.match_entities("Carrefour campaign review")
        first, created = self.db.save_calendar_event(
            self.event(), [match["id"] for match in matches]
        )
        updated_event = self.event("Carrefour final campaign review")
        second, created_again = self.db.save_calendar_event(
            updated_event, [match["id"] for match in matches]
        )
        entity = self.db.get_entity("Carrefour")
        context = self.db.entity_context(entity["id"])
        timeline = self.db.entity_timeline(entity["id"])

        self.assertTrue(created)
        self.assertFalse(created_again)
        self.assertEqual(first["id"], second["id"])
        self.assertEqual(second["title"], "Carrefour final campaign review")
        self.assertEqual(len(context["calendar_events"]), 1)
        self.assertIn("calendar_event", {event["type"] for event in timeline["events"]})

    def test_unmatched_event_can_be_stored_without_invented_entity(self):
        matches = self.db.match_entities("Unrelated internal meeting")
        event, created = self.db.save_calendar_event(self.event("Internal meeting"), [])

        self.assertEqual(matches, [])
        self.assertTrue(created)
        listed = self.db.list_calendar_events()
        self.assertIsNone(listed[0]["entity_names"])

    def test_failed_calendar_action_can_be_corrected_for_new_approval(self):
        _, _, action_id = self.db.save_analysis(
            EmailRequest(subject="Meeting", body="Schedule a meeting"),
            EmailAnalysis(
                category="meeting", summary="Meeting requested.",
                work_items=[EmailWorkItem(
                    kind="meeting", title="Planning call", proposed_action="Create meeting",
                    start_at="2030-09-18T10:00:00+02:00",
                    end_at="2030-09-18T10:30:00+02:00",
                )],
            ),
        )
        from models import ActionStatus
        self.db.decide_action(action_id, ActionStatus.APPROVED, "Approved")
        self.db.claim_approved_action(action_id)
        self.db.fail_action(action_id, "Temporary failure")

        updated = self.db.update_action_payload(
            action_id,
            {"calendar_event": {
                "title": "Planning call", "start_at": "2030-09-18T11:00:00+02:00",
                "end_at": "2030-09-18T11:30:00+02:00", "location": None, "attendees": [],
            }},
            {"calendar_event"}, allow_failed_retry=True,
        )

        self.assertEqual(updated["status"], "pending_approval")
        self.assertIsNone(updated["error_message"])


if __name__ == "__main__":
    unittest.main()
