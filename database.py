import json
import re
import sqlite3
from contextlib import contextmanager
from pathlib import Path

from models import ActionStatus, EmailAnalysis


def normalize_entity_name(name: str) -> str:
    return " ".join(re.sub(r"[^a-z0-9]+", " ", name.casefold()).split())


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
                CREATE TABLE IF NOT EXISTS entities (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    normalized_name TEXT NOT NULL UNIQUE,
                    entity_type TEXT NOT NULL DEFAULT 'unknown',
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS entity_aliases (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    entity_id INTEGER NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
                    alias TEXT NOT NULL,
                    normalized_alias TEXT NOT NULL UNIQUE
                );
                CREATE TABLE IF NOT EXISTS email_entities (
                    email_id INTEGER NOT NULL REFERENCES emails(id) ON DELETE CASCADE,
                    entity_id INTEGER NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
                    PRIMARY KEY (email_id, entity_id)
                );
                CREATE TABLE IF NOT EXISTS decisions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    entity_id INTEGER NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
                    title TEXT NOT NULL,
                    decision TEXT NOT NULL,
                    rationale TEXT,
                    status TEXT NOT NULL DEFAULT 'final',
                    source_email_id INTEGER REFERENCES emails(id),
                    decided_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE INDEX IF NOT EXISTS idx_commitments_status_deadline ON commitments(status, deadline);
                CREATE INDEX IF NOT EXISTS idx_actions_status ON proposed_actions(status);
                CREATE INDEX IF NOT EXISTS idx_decisions_entity ON decisions(entity_id, decided_at);
                """
            )
            self._backfill_entities(connection)

    @staticmethod
    def _ensure_entity(connection, name: str):
        normalized = normalize_entity_name(name)
        if not normalized:
            return None
        row = connection.execute(
            """SELECT e.* FROM entities e
               LEFT JOIN entity_aliases a ON a.entity_id = e.id
               WHERE e.normalized_name = ? OR a.normalized_alias = ?
               LIMIT 1""",
            (normalized, normalized),
        ).fetchone()
        if row:
            return row["id"]
        cursor = connection.execute(
            "INSERT INTO entities (name, normalized_name) VALUES (?, ?)",
            (name.strip(), normalized),
        )
        return cursor.lastrowid

    def _backfill_entities(self, connection):
        rows = connection.execute(
            """SELECT e.id, e.analysis_json, c.company_or_project
               FROM emails e
               LEFT JOIN commitments c ON c.email_id = e.id
               WHERE NOT EXISTS (
                   SELECT 1 FROM email_entities ee WHERE ee.email_id = e.id
               )"""
        ).fetchall()
        for row in rows:
            name = row["company_or_project"]
            if not name and row["analysis_json"]:
                try:
                    name = json.loads(row["analysis_json"]).get("company_or_project")
                except (TypeError, json.JSONDecodeError):
                    name = None
            if name:
                entity_id = self._ensure_entity(connection, name)
                connection.execute(
                    "INSERT OR IGNORE INTO email_entities (email_id, entity_id) VALUES (?, ?)",
                    (row["id"], entity_id),
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
            if analysis.company_or_project:
                entity_id = self._ensure_entity(connection, analysis.company_or_project)
                connection.execute(
                    "INSERT INTO email_entities (email_id, entity_id) VALUES (?, ?)",
                    (email_id, entity_id),
                )
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

    def list_entities(self):
        with self.connect() as connection:
            rows = connection.execute(
                """SELECT e.*, COUNT(DISTINCT ee.email_id) AS email_count,
                          COUNT(DISTINCT CASE WHEN c.status = 'open' THEN c.id END) AS open_commitment_count
                   FROM entities e
                   LEFT JOIN email_entities ee ON ee.entity_id = e.id
                   LEFT JOIN commitments c ON c.email_id = ee.email_id
                   GROUP BY e.id ORDER BY e.name"""
            ).fetchall()
            return [dict(row) for row in rows]

    def get_entity(self, name_or_alias: str):
        normalized = normalize_entity_name(name_or_alias)
        with self.connect() as connection:
            row = connection.execute(
                """SELECT DISTINCT e.* FROM entities e
                   LEFT JOIN entity_aliases a ON a.entity_id = e.id
                   WHERE e.normalized_name = ? OR a.normalized_alias = ?""",
                (normalized, normalized),
            ).fetchone()
            return dict(row) if row else None

    def add_decision(self, entity_id: int, request):
        with self.connect() as connection:
            if request.source_email_id is not None:
                linked = connection.execute(
                    "SELECT 1 FROM email_entities WHERE entity_id = ? AND email_id = ?",
                    (entity_id, request.source_email_id),
                ).fetchone()
                if not linked:
                    raise ValueError("Source email is not linked to this entity")
            cursor = connection.execute(
                """INSERT INTO decisions
                   (entity_id, title, decision, rationale, status, source_email_id)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (entity_id, request.title, request.decision, request.rationale,
                 request.status, request.source_email_id),
            )
            decision_id = cursor.lastrowid
            connection.execute(
                """INSERT INTO audit_log (entity_type, entity_id, event, details_json)
                   VALUES ('decision', ?, 'recorded', ?)""",
                (decision_id, json.dumps({"entity_id": entity_id, "status": request.status})),
            )
            return dict(connection.execute(
                "SELECT * FROM decisions WHERE id = ?", (decision_id,)
            ).fetchone())

    def entity_context(self, entity_id: int):
        with self.connect() as connection:
            entity = connection.execute("SELECT * FROM entities WHERE id = ?", (entity_id,)).fetchone()
            if not entity:
                return None
            emails = connection.execute(
                """SELECT e.id, e.sender, e.subject, e.category, e.summary, e.created_at
                   FROM emails e JOIN email_entities ee ON ee.email_id = e.id
                   WHERE ee.entity_id = ? ORDER BY e.created_at DESC""", (entity_id,)
            ).fetchall()
            commitments = connection.execute(
                """SELECT c.* FROM commitments c JOIN email_entities ee ON ee.email_id = c.email_id
                   WHERE ee.entity_id = ? ORDER BY c.created_at DESC""", (entity_id,)
            ).fetchall()
            actions = connection.execute(
                """SELECT a.id, a.action_type, a.description, a.status, a.decision_note,
                          a.created_at, a.decided_at, a.executed_at
                   FROM proposed_actions a JOIN email_entities ee ON ee.email_id = a.email_id
                   WHERE ee.entity_id = ? ORDER BY a.created_at DESC""", (entity_id,)
            ).fetchall()
            decisions = connection.execute(
                "SELECT * FROM decisions WHERE entity_id = ? ORDER BY decided_at DESC", (entity_id,)
            ).fetchall()
            return {
                "entity": dict(entity),
                "emails": [dict(row) for row in emails],
                "commitments": [dict(row) for row in commitments],
                "actions": [dict(row) for row in actions],
                "decisions": [dict(row) for row in decisions],
            }

    def entity_timeline(self, entity_id: int):
        context = self.entity_context(entity_id)
        if context is None:
            return None
        events = []
        for email in context["emails"]:
            events.append({"type": "email", "timestamp": email["created_at"], "data": email})
        for commitment in context["commitments"]:
            events.append({"type": "commitment", "timestamp": commitment["created_at"], "data": commitment})
        for action in context["actions"]:
            events.append({"type": "action", "timestamp": action["created_at"], "data": action})
        for decision in context["decisions"]:
            events.append({"type": "decision", "timestamp": decision["decided_at"], "data": decision})
        events.sort(key=lambda event: event["timestamp"] or "", reverse=True)
        return {"entity": context["entity"], "events": events}
