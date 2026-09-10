import json
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


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

    def create_event(self, proposal: dict, calendar_id: str = "primary"):
        body = {
            "summary": proposal["title"],
            "start": {"dateTime": proposal["start_at"]},
            "end": {"dateTime": proposal["end_at"]},
        }
        if proposal.get("location"):
            body["location"] = proposal["location"]
        if proposal.get("attendees"):
            body["attendees"] = [{"email": email} for email in proposal["attendees"]]
        created = self.service.events().insert(
            calendarId=calendar_id, body=body, sendUpdates="none"
        ).execute()
        return {"provider": "google_calendar", "event_id": created.get("id"),
                "html_link": created.get("htmlLink"), "attendee_updates_sent": False}

    def suggest_interview_slots(
        self,
        preference_text: str = "",
        calendar_id: str = "primary",
        count: int = 3,
        now: datetime | None = None,
        timezone_name: str = "Europe/Amsterdam",
    ):
        """Return free 30-minute business-hour slots, biased by stated preferences."""
        try:
            local_timezone = ZoneInfo(timezone_name)
        except ZoneInfoNotFoundError:
            # Some minimal Windows Python installations do not ship the IANA database.
            # The computer's configured local offset is still preferable to silently
            # treating interview times as UTC.
            local_timezone = datetime.now().astimezone().tzinfo or timezone.utc
        now = now or datetime.now(local_timezone)
        if now.tzinfo is None:
            now = now.replace(tzinfo=local_timezone)
        now = now.astimezone(local_timezone)
        events = self.list_events(
            calendar_id=calendar_id, days_before=0, days_after=21, now=now
        )
        busy = []
        all_day_dates = set()
        for event in events:
            if event.get("status") == "cancelled":
                continue
            if event.get("all_day"):
                try:
                    all_day_dates.add(datetime.fromisoformat(event["start_at"]).date())
                except (TypeError, ValueError):
                    pass
                continue
            try:
                start = datetime.fromisoformat(event["start_at"].replace("Z", "+00:00"))
                end = datetime.fromisoformat(event["end_at"].replace("Z", "+00:00"))
            except (AttributeError, TypeError, ValueError):
                continue
            if start.tzinfo is None:
                start = start.replace(tzinfo=local_timezone)
            if end.tzinfo is None:
                end = end.replace(tzinfo=local_timezone)
            busy.append((start.astimezone(local_timezone), end.astimezone(local_timezone)))

        text = (preference_text or "").casefold()
        weekday_terms = {
            0: ("monday", "maandag"), 1: ("tuesday", "dinsdag"),
            2: ("wednesday", "woensdag"), 3: ("thursday", "donderdag"),
            4: ("friday", "vrijdag"),
        }
        preferred_days = {
            day for day, terms in weekday_terms.items() if any(term in text for term in terms)
        }
        if any(term in text for term in ("afternoon", "middag")):
            hours = range(13, 17)
            period = "afternoon"
        elif any(term in text for term in ("morning", "ochtend")):
            hours = range(9, 12)
            period = "morning"
        else:
            hours = range(9, 17)
            period = None

        first_date = (now + timedelta(days=1)).date()
        if "next week" in text or "volgende week" in text:
            first_date += timedelta(days=(7 - first_date.weekday()) % 7)
        candidates = []
        for day_offset in range(21):
            date = first_date + timedelta(days=day_offset)
            if date.weekday() > 4 or date in all_day_dates:
                continue
            preference_match = not preferred_days or date.weekday() in preferred_days
            for hour in hours:
                for minute in (0, 30):
                    start = datetime(date.year, date.month, date.day, hour, minute,
                                     tzinfo=local_timezone)
                    end = start + timedelta(minutes=30)
                    if start <= now or any(start < busy_end and end > busy_start
                                           for busy_start, busy_end in busy):
                        continue
                    reason_parts = []
                    if date.weekday() in preferred_days:
                        reason_parts.append(start.strftime("%A"))
                    if period:
                        reason_parts.append(period)
                    candidates.append((not preference_match, start, end, " ".join(reason_parts)))
        candidates.sort(key=lambda item: (item[0], item[1]))
        return [
            {
                "start_at": start.isoformat(), "end_at": end.isoformat(),
                "label": start.strftime("%a %d %b, %H:%M"),
                "preference_match": not fallback,
                "reason": reason or "Available in working hours",
            }
            for fallback, start, end, reason in candidates[:count]
        ]

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
