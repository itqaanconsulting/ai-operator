import json
from datetime import datetime, timedelta, timezone


class CalendarOperator:
    def __init__(self, service):
        self.service = service

    def list_events(
        self,
        calendar_id: str = "primary",
        days_before: int = 30,
        days_after: int = 90,
        now: datetime | None = None,
    ):
        now = now or datetime.now(timezone.utc)
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)
        time_min = (now - timedelta(days=days_before)).isoformat()
        time_max = (now + timedelta(days=days_after)).isoformat()
        response = self.service.events().list(
            calendarId=calendar_id,
            timeMin=time_min,
            timeMax=time_max,
            singleEvents=True,
            orderBy="startTime",
            maxResults=2500,
        ).execute()
        return [self._normalize_event(event, calendar_id) for event in response.get("items", [])]

    @staticmethod
    def _normalize_event(event: dict, calendar_id: str):
        start = event.get("start", {})
        end = event.get("end", {})
        attendees = [
            attendee.get("email") for attendee in event.get("attendees", [])
            if attendee.get("email")
        ]
        return {
            "google_event_id": event["id"],
            "calendar_id": calendar_id,
            "title": event.get("summary") or "(untitled event)",
            "description": event.get("description"),
            "location": event.get("location"),
            "start_at": start.get("dateTime") or start.get("date"),
            "end_at": end.get("dateTime") or end.get("date"),
            "all_day": "date" in start,
            "status": event.get("status", "confirmed"),
            "attendees_json": json.dumps(attendees),
            "html_link": event.get("htmlLink"),
            "meeting_link": event.get("hangoutLink"),
            "updated_at_source": event.get("updated"),
        }
