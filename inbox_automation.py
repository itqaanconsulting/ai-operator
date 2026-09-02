from open_loops import OpenLoopMonitor


class InboxAutomation:
    """Turn a bounded Gmail read into analyzed work and proactive reminders."""

    def __init__(self, database, analyzer):
        self.database = database
        self.analyzer = analyzer

    def run(self, emails, due_within_days: int = 3):
        emails = list(emails)
        result = {"found": len(emails), "processed": [], "skipped": [], "errors": []}
        for email in emails:
            if email.gmail_msg_id and self.database.email_exists(email.gmail_msg_id):
                result["skipped"].append(email.gmail_msg_id)
                continue
            try:
                analysis = self.analyzer.analyze(email)
                email_id, commitment_id, action_id = self.database.save_analysis(email, analysis)
                result["processed"].append({
                    "gmail_msg_id": email.gmail_msg_id,
                    "email_id": email_id,
                    "commitment_id": commitment_id,
                    "action_id": action_id,
                })
            except Exception as exc:
                result["errors"].append({"gmail_msg_id": email.gmail_msg_id, "error": str(exc)})
        result["open_loop_monitor"] = OpenLoopMonitor(self.database).run(due_within_days)
        return result
