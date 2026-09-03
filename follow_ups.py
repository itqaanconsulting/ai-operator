from datetime import datetime, timezone


def normalize_follow_up_time(value: str) -> str:
    parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).isoformat()


class FollowUpMonitor:
    def __init__(self, database):
        self.database = database

    def run(self, now: datetime | None = None):
        now = now or datetime.now(timezone.utc)
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)
        return self.database.trigger_due_follow_ups(now.astimezone(timezone.utc).isoformat())
