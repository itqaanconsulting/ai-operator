from datetime import date, datetime, time, timedelta, timezone


def parse_deadline(value: str) -> datetime:
    normalized = value.strip().replace("Z", "+00:00")
    if len(normalized) == 10:
        parsed_date = date.fromisoformat(normalized)
        return datetime.combine(parsed_date, time.max, tzinfo=timezone.utc)
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


class OpenLoopMonitor:
    def __init__(self, database):
        self.database = database

    def run(self, due_within_days: int, now: datetime | None = None):
        now = now or datetime.now(timezone.utc)
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)
        threshold = now + timedelta(days=due_within_days)
        result = {
            "checked": 0,
            "created": [],
            "existing": [],
            "missing_deadline": [],
            "invalid_deadline": [],
            "not_due": [],
            "covered_by_primary_action": [],
        }
        for commitment in self.database.list_open_commitments():
            result["checked"] += 1
            if not commitment.get("deadline"):
                result["missing_deadline"].append(commitment["id"])
                continue
            try:
                deadline = parse_deadline(commitment["deadline"])
            except ValueError:
                result["invalid_deadline"].append({
                    "commitment_id": commitment["id"],
                    "deadline": commitment["deadline"],
                })
                continue
            if deadline < now:
                alert_type = "overdue"
            elif deadline <= threshold:
                alert_type = "due_soon"
            else:
                result["not_due"].append(commitment["id"])
                continue
            if self.database.has_active_primary_action(commitment["id"]):
                result["covered_by_primary_action"].append(commitment["id"])
                continue
            action, created = self.database.create_open_loop_alert(commitment, alert_type)
            item = {"commitment_id": commitment["id"], "action_id": action["id"],
                    "alert_type": alert_type}
            result["created" if created else "existing"].append(item)
        return result
