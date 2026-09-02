import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path

from models import ActionStatus, EmailAnalysis


class Database:
    def __init__(self, path: str = "operator.db"):
        self.path = Path(path)

    @contextmanager
    def connect(self):
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        try:
            yield connection
            connection.commit()
        finally:
            connection.close()

    def init(self):
        with self.connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS emails (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    gmail_msg_id TEXT UNIQUE,
                    sender TEXT,
                    subject TEXT NOT NULL,
                    body TEXT NOT NULL,
                    category TEXT,
                    summary TEXT,
                    analysis_json TEXT,
                    processing_status TEXT NOT NULL DEFAULT 'processed',
                    error_message TEXT,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS commitments (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    email_id INTEGER NOT NULL REFERENCES emails(id),
                    title TEXT NOT NULL,
                    contact_name TEXT,
                    company_or_project TEXT,
                    deadline TEXT,
                    urgency TEXT NOT NULL DEFAULT 'medium',
                    status TEXT NOT NULL DEFAULT 'open',
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    completed_at TEXT
                );
                CREATE TABLE IF NOT EXISTS proposed_actions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    commitment_id INTEGER REFERENCES commitments(id),
                    email_id INTEGER NOT NULL REFERENCES emails(id),
                    action_type TEXT NOT NULL,
                    description TEXT NOT NULL,
                    payload_json TEXT NOT NULL DEFAULT '{}',
                    status TEXT NOT NULL DEFAULT 'pending_approval',
                    decision_note TEXT,
                    decided_at TEXT,
                    executed_at TEXT,
                    error_message TEXT,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS audit_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    entity_type TEXT NOT NULL,
                    entity_id INTEGER NOT NULL,
                    event TEXT NOT NULL,
                    details_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE INDEX IF NOT EXISTS idx_commitments_status_deadline ON commitments(status, deadline);
                CREATE INDEX IF NOT EXISTS idx_actions_status ON proposed_actions(status);
                """
            )

    def save_analysis(self, request, analysis: EmailAnalysis):
        with self.connect() as connection:
            if request.gmail_msg_id:
                existing = connection.execute(
                    "SELECT id FROM emails WHERE gmail_msg_id = ?", (request.gmail_msg_id,)
                ).fetchone()
                if existing:
                    return existing["id"], None, None
            cursor = connection.execute(
                """INSERT INTO emails
                   (gmail_msg_id, sender, subject, body, category, summary, analysis_json)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (request.gmail_msg_id, request.sender, request.subject, request.body,
                 analysis.category, analysis.summary, analysis.model_dump_json()),
            )
            email_id = cursor.lastrowid
            commitment_id = None
            action_id = None
            if analysis.commitment_title:
                cursor = connection.execute(
                    """INSERT INTO commitments
                       (email_id, title, contact_name, company_or_project, deadline, urgency)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    (email_id, analysis.commitment_title, analysis.contact_name,
                     analysis.company_or_project, analysis.deadline, analysis.urgency),
                )
                commitment_id = cursor.lastrowid
            if analysis.proposed_action:
                action_type = "draft_reply" if analysis.suggested_reply else "review"
                cursor = connection.execute(
                    """INSERT INTO proposed_actions
                       (commitment_id, email_id, action_type, description, payload_json, status)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    (commitment_id, email_id, action_type, analysis.proposed_action,
                     json.dumps({"suggested_reply": analysis.suggested_reply}),
                     ActionStatus.PENDING_APPROVAL.value),
                )
                action_id = cursor.lastrowid
            connection.execute(
                "INSERT INTO audit_log (entity_type, entity_id, event) VALUES ('email', ?, 'analyzed')",
                (email_id,),
            )
            return email_id, commitment_id, action_id

    def email_exists(self, gmail_msg_id: str) -> bool:
        with self.connect() as connection:
            return connection.execute(
                "SELECT 1 FROM emails WHERE gmail_msg_id = ?", (gmail_msg_id,)
            ).fetchone() is not None

    def list_rows(self, table: str, status: str | None = None):
        if table not in {"commitments", "proposed_actions"}:
            raise ValueError("Unsupported table")
        query = f"SELECT * FROM {table}"
        params = ()
        if status:
            query += " WHERE status = ?"
            params = (status,)
        with self.connect() as connection:
            rows = connection.execute(query + " ORDER BY id DESC", params).fetchall()
            return [dict(row) for row in rows]

    def decide_action(self, action_id: int, status: ActionStatus, note: str | None):
        if status not in {ActionStatus.APPROVED, ActionStatus.REJECTED}:
            raise ValueError("Invalid decision")
        with self.connect() as connection:
            cursor = connection.execute(
                """UPDATE proposed_actions SET status = ?, decision_note = ?, decided_at = CURRENT_TIMESTAMP
                   WHERE id = ? AND status = ?""",
                (status.value, note, action_id, ActionStatus.PENDING_APPROVAL.value),
            )
            if cursor.rowcount == 0:
                return None
            connection.execute(
                """INSERT INTO audit_log (entity_type, entity_id, event, details_json)
                   VALUES ('action', ?, ?, ?)""",
                (action_id, status.value, json.dumps({"note": note})),
            )
            row = connection.execute("SELECT * FROM proposed_actions WHERE id = ?", (action_id,)).fetchone()
            return dict(row)

    def claim_approved_action(self, action_id: int):
        """Atomically claim one approved action for external execution."""
        with self.connect() as connection:
            cursor = connection.execute(
                """UPDATE proposed_actions SET status = ?
                   WHERE id = ? AND status = ?""",
                (ActionStatus.EXECUTING.value, action_id, ActionStatus.APPROVED.value),
            )
            if cursor.rowcount == 0:
                return None
            row = connection.execute(
                """SELECT a.*, e.gmail_msg_id, e.sender, e.subject
                   FROM proposed_actions a
                   JOIN emails e ON e.id = a.email_id
                   WHERE a.id = ?""",
                (action_id,),
            ).fetchone()
            return dict(row)

    def finish_action(self, action_id: int, external_result: dict):
        with self.connect() as connection:
            current = connection.execute(
                "SELECT payload_json FROM proposed_actions WHERE id = ? AND status = ?",
                (action_id, ActionStatus.EXECUTING.value),
            ).fetchone()
            if current is None:
                return None
            payload = json.loads(current["payload_json"] or "{}")
            payload["external_result"] = external_result
            cursor = connection.execute(
                """UPDATE proposed_actions
                   SET status = ?, executed_at = CURRENT_TIMESTAMP,
                       payload_json = ?
                   WHERE id = ? AND status = ?""",
                (ActionStatus.EXECUTED.value, json.dumps(payload),
                 action_id, ActionStatus.EXECUTING.value),
            )
            if cursor.rowcount == 0:
                return None
            connection.execute(
                """INSERT INTO audit_log (entity_type, entity_id, event, details_json)
                   VALUES ('action', ?, 'executed', ?)""",
                (action_id, json.dumps(external_result)),
            )
            return dict(connection.execute(
                "SELECT * FROM proposed_actions WHERE id = ?", (action_id,)
            ).fetchone())

    def fail_action(self, action_id: int, error_message: str):
        with self.connect() as connection:
            connection.execute(
                """UPDATE proposed_actions
                   SET status = ?, error_message = ?
                   WHERE id = ? AND status = ?""",
                (ActionStatus.FAILED.value, error_message[:2000], action_id,
                 ActionStatus.EXECUTING.value),
            )
            connection.execute(
                """INSERT INTO audit_log (entity_type, entity_id, event, details_json)
                   VALUES ('action', ?, 'failed', ?)""",
                (action_id, json.dumps({"error": error_message[:2000]})),
            )
