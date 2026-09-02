import threading


class AutomationScheduler:
    """Small local scheduler. Disabled by default; executes only claimed due work."""

    def __init__(self, database, contract_intake_callback, inbox_callback=None,
                 check_seconds: int = 15):
        self.database = database
        self.contract_intake_callback = contract_intake_callback
        self.inbox_callback = inbox_callback
        self.check_seconds = check_seconds
        self._stop = threading.Event()
        self._thread = None

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True, name="contract-intake-scheduler")
        self._thread.start()

    def stop(self):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2)

    def _run(self):
        while not self._stop.wait(self.check_seconds):
            schedule = self.database.claim_due_contract_schedule()
            if schedule:
                try:
                    result = self.contract_intake_callback(
                        schedule["label"], schedule["max_messages"], "scheduled"
                    )
                    self.database.finish_contract_schedule(result=result)
                except Exception as exc:
                    self.database.finish_contract_schedule(error=str(exc))
            if not self.inbox_callback:
                continue
            inbox_schedule = self.database.claim_due_inbox_schedule()
            if not inbox_schedule:
                continue
            try:
                result = self.inbox_callback(
                    inbox_schedule["label"], inbox_schedule["max_results"], "scheduled"
                )
                self.database.finish_inbox_schedule(result=result)
            except Exception as exc:
                self.database.finish_inbox_schedule(error=str(exc))
