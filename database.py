import json
import re
import sqlite3
from contextlib import contextmanager
from pathlib import Path

from models import (
    ActionStatus, DocumentAnalysis, DocumentComparison, EmailAnalysis, RevisionRequestDraft,
)


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
                CREATE TABLE IF NOT EXISTS open_loop_alerts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    commitment_id INTEGER NOT NULL REFERENCES commitments(id) ON DELETE CASCADE,
                    alert_type TEXT NOT NULL,
                    deadline_snapshot TEXT NOT NULL,
                    proposed_action_id INTEGER NOT NULL REFERENCES proposed_actions(id),
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE (commitment_id, alert_type, deadline_snapshot)
                );
                CREATE TABLE IF NOT EXISTS calendar_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    google_event_id TEXT NOT NULL,
                    calendar_id TEXT NOT NULL,
                    title TEXT NOT NULL,
                    description TEXT,
                    location TEXT,
                    start_at TEXT,
                    end_at TEXT,
                    all_day INTEGER NOT NULL DEFAULT 0,
                    status TEXT NOT NULL DEFAULT 'confirmed',
                    attendees_json TEXT NOT NULL DEFAULT '[]',
                    html_link TEXT,
                    meeting_link TEXT,
                    updated_at_source TEXT,
                    imported_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE (google_event_id, calendar_id)
                );
                CREATE TABLE IF NOT EXISTS calendar_event_entities (
                    calendar_event_id INTEGER NOT NULL REFERENCES calendar_events(id) ON DELETE CASCADE,
                    entity_id INTEGER NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
                    PRIMARY KEY (calendar_event_id, entity_id)
                );
                CREATE TABLE IF NOT EXISTS documents (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    filename TEXT NOT NULL,
                    mime_type TEXT,
                    sha256 TEXT NOT NULL UNIQUE,
                    document_type TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    analysis_json TEXT NOT NULL,
                    extracted_text TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS document_entities (
                    document_id INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
                    entity_id INTEGER NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
                    PRIMARY KEY (document_id, entity_id)
                );
                CREATE TABLE IF NOT EXISTS document_comparisons (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    candidate_filename TEXT NOT NULL,
                    candidate_sha256 TEXT NOT NULL,
                    reference_filename TEXT NOT NULL,
                    reference_sha256 TEXT NOT NULL,
                    executive_summary TEXT NOT NULL,
                    comparison_json TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE (candidate_sha256, reference_sha256)
                );
                CREATE TABLE IF NOT EXISTS document_comparison_entities (
                    comparison_id INTEGER NOT NULL REFERENCES document_comparisons(id) ON DELETE CASCADE,
                    entity_id INTEGER NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
                    PRIMARY KEY (comparison_id, entity_id)
                );
                CREATE TABLE IF NOT EXISTS document_review_decisions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    comparison_id INTEGER NOT NULL UNIQUE
                        REFERENCES document_comparisons(id) ON DELETE CASCADE,
                    decision TEXT NOT NULL CHECK (
                        decision IN ('approved', 'revision_requested', 'rejected')
                    ),
                    note TEXT NOT NULL,
                    decided_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS document_revision_drafts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    comparison_id INTEGER NOT NULL UNIQUE
                        REFERENCES document_comparisons(id) ON DELETE CASCADE,
                    subject TEXT NOT NULL,
                    body TEXT NOT NULL,
                    requested_changes_json TEXT NOT NULL DEFAULT '[]',
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS revision_draft_deliveries (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    revision_draft_id INTEGER NOT NULL UNIQUE
                        REFERENCES document_revision_drafts(id) ON DELETE CASCADE,
                    recipient TEXT NOT NULL,
                    approval_note TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'approved',
                    provider_draft_id TEXT,
                    error_message TEXT,
                    approved_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    executed_at TEXT
                );
                CREATE TABLE IF NOT EXISTS gmail_attachment_imports (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    gmail_msg_id TEXT NOT NULL,
                    attachment_id TEXT NOT NULL,
                    document_id INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
                    filename TEXT NOT NULL,
                    subject TEXT,
                    sender TEXT,
                    imported_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE (gmail_msg_id, attachment_id)
                );
                CREATE INDEX IF NOT EXISTS idx_commitments_status_deadline ON commitments(status, deadline);
                CREATE INDEX IF NOT EXISTS idx_actions_status ON proposed_actions(status);
                CREATE INDEX IF NOT EXISTS idx_decisions_entity ON decisions(entity_id, decided_at);
                CREATE INDEX IF NOT EXISTS idx_open_loop_alerts_commitment ON open_loop_alerts(commitment_id);
                CREATE INDEX IF NOT EXISTS idx_calendar_events_start ON calendar_events(start_at);
                CREATE INDEX IF NOT EXISTS idx_document_entities_entity ON document_entities(entity_id);
                CREATE INDEX IF NOT EXISTS idx_comparison_entities_entity
                    ON document_comparison_entities(entity_id);
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

    def save_document(self, filename: str, mime_type: str | None, sha256: str,
                      extracted_text: str, analysis: DocumentAnalysis):
        with self.connect() as connection:
            existing = connection.execute(
                "SELECT * FROM documents WHERE sha256 = ?", (sha256,)
            ).fetchone()
            if existing:
                entity = connection.execute(
                    "SELECT entity_id FROM document_entities WHERE document_id = ? LIMIT 1",
                    (existing["id"],),
                ).fetchone()
                return dict(existing), entity["entity_id"] if entity else None, True
            cursor = connection.execute(
                """INSERT INTO documents
                   (filename, mime_type, sha256, document_type, summary, analysis_json, extracted_text)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (filename, mime_type, sha256, analysis.document_type, analysis.summary,
                 analysis.model_dump_json(), extracted_text),
            )
            document_id = cursor.lastrowid
            entity_id = None
            if analysis.company_or_project:
                entity_id = self._ensure_entity(connection, analysis.company_or_project)
                connection.execute(
                    "INSERT INTO document_entities (document_id, entity_id) VALUES (?, ?)",
                    (document_id, entity_id),
                )
            connection.execute(
                """INSERT INTO audit_log (entity_type, entity_id, event, details_json)
                   VALUES ('document', ?, 'analyzed', ?)""",
                (document_id, json.dumps({"filename": filename, "entity_id": entity_id})),
            )
            row = connection.execute("SELECT * FROM documents WHERE id = ?", (document_id,)).fetchone()
            return dict(row), entity_id, False

    def list_documents(self):
        with self.connect() as connection:
            rows = connection.execute(
                """SELECT d.id, d.filename, d.mime_type, d.document_type, d.summary,
                          d.analysis_json, d.created_at,
                          GROUP_CONCAT(DISTINCT e.name) AS entity_names
                   FROM documents d
                   LEFT JOIN document_entities de ON de.document_id = d.id
                   LEFT JOIN entities e ON e.id = de.entity_id
                   GROUP BY d.id ORDER BY d.created_at DESC"""
            ).fetchall()
            return [dict(row) for row in rows]

    def get_document_by_sha256(self, sha256: str):
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM documents WHERE sha256 = ?", (sha256,)
            ).fetchone()
            return dict(row) if row else None

    def gmail_attachment_import_exists(self, gmail_msg_id: str, attachment_id: str):
        with self.connect() as connection:
            return connection.execute(
                """SELECT 1 FROM gmail_attachment_imports
                   WHERE gmail_msg_id = ? AND attachment_id = ?""",
                (gmail_msg_id, attachment_id),
            ).fetchone() is not None

    def link_gmail_attachment(self, document_id: int, attachment: dict):
        with self.connect() as connection:
            try:
                cursor = connection.execute(
                    """INSERT INTO gmail_attachment_imports
                       (gmail_msg_id, attachment_id, document_id, filename, subject, sender)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    (attachment["gmail_msg_id"], attachment["attachment_id"], document_id,
                     attachment["filename"], attachment.get("subject"), attachment.get("sender")),
                )
            except sqlite3.IntegrityError:
                return None, False
            connection.execute(
                """INSERT INTO audit_log (entity_type, entity_id, event, details_json)
                   VALUES ('document', ?, 'gmail_attachment_imported', ?)""",
                (document_id, json.dumps({
                    "gmail_msg_id": attachment["gmail_msg_id"],
                    "attachment_id": attachment["attachment_id"],
                    "filename": attachment["filename"],
                })),
            )
            row = connection.execute(
                "SELECT * FROM gmail_attachment_imports WHERE id = ?", (cursor.lastrowid,)
            ).fetchone()
            return dict(row), True

    def save_document_comparison(self, candidate_filename: str, candidate_sha256: str,
                                 reference_filename: str, reference_sha256: str,
                                 comparison: DocumentComparison):
        with self.connect() as connection:
            existing = connection.execute(
                """SELECT * FROM document_comparisons
                   WHERE candidate_sha256 = ? AND reference_sha256 = ?""",
                (candidate_sha256, reference_sha256),
            ).fetchone()
            if existing:
                linked = connection.execute(
                    """SELECT entity_id FROM document_comparison_entities
                       WHERE comparison_id = ? LIMIT 1""", (existing["id"],)
                ).fetchone()
                return dict(existing), linked["entity_id"] if linked else None, True
            cursor = connection.execute(
                """INSERT INTO document_comparisons
                   (candidate_filename, candidate_sha256, reference_filename, reference_sha256,
                    executive_summary, comparison_json) VALUES (?, ?, ?, ?, ?, ?)""",
                (candidate_filename, candidate_sha256, reference_filename, reference_sha256,
                 comparison.executive_summary, comparison.model_dump_json()),
            )
            comparison_id = cursor.lastrowid
            entity_id = None
            if comparison.company_or_project:
                entity_id = self._ensure_entity(connection, comparison.company_or_project)
                connection.execute(
                    """INSERT INTO document_comparison_entities (comparison_id, entity_id)
                       VALUES (?, ?)""", (comparison_id, entity_id)
                )
            connection.execute(
                """INSERT INTO audit_log (entity_type, entity_id, event, details_json)
                   VALUES ('document_comparison', ?, 'compared', ?)""",
                (comparison_id, json.dumps({"entity_id": entity_id,
                                            "candidate": candidate_filename,
                                            "reference": reference_filename})),
            )
            row = connection.execute(
                "SELECT * FROM document_comparisons WHERE id = ?", (comparison_id,)
            ).fetchone()
            return dict(row), entity_id, False

    def list_document_comparisons(self):
        with self.connect() as connection:
            rows = connection.execute(
                """SELECT dc.*, GROUP_CONCAT(DISTINCT e.name) AS entity_names,
                          COALESCE(drd.decision, 'pending_review') AS review_status,
                          drd.note AS review_note, drd.decided_at
                   FROM document_comparisons dc
                   LEFT JOIN document_comparison_entities dce ON dce.comparison_id = dc.id
                   LEFT JOIN entities e ON e.id = dce.entity_id
                   LEFT JOIN document_review_decisions drd ON drd.comparison_id = dc.id
                   GROUP BY dc.id ORDER BY dc.created_at DESC"""
            ).fetchall()
            return [dict(row) for row in rows]

    def decide_document_comparison(self, comparison_id: int, decision: str, note: str):
        allowed = {"approved", "revision_requested", "rejected"}
        if decision not in allowed:
            raise ValueError("Invalid document review decision")
        with self.connect() as connection:
            exists = connection.execute(
                "SELECT 1 FROM document_comparisons WHERE id = ?", (comparison_id,)
            ).fetchone()
            if not exists:
                return None, "not_found"
            try:
                cursor = connection.execute(
                    """INSERT INTO document_review_decisions (comparison_id, decision, note)
                       VALUES (?, ?, ?)""", (comparison_id, decision, note.strip())
                )
            except sqlite3.IntegrityError:
                return None, "already_decided"
            connection.execute(
                """INSERT INTO audit_log (entity_type, entity_id, event, details_json)
                   VALUES ('document_comparison', ?, ?, ?)""",
                (comparison_id, decision, json.dumps({"note": note.strip()})),
            )
            row = connection.execute(
                "SELECT * FROM document_review_decisions WHERE id = ?", (cursor.lastrowid,)
            ).fetchone()
            return dict(row), None

    def get_revision_draft_context(self, comparison_id: int):
        with self.connect() as connection:
            row = connection.execute(
                """SELECT dc.id, dc.candidate_filename, dc.reference_filename,
                          dc.comparison_json, drd.decision, drd.note,
                          drd.decided_at, draft.id AS draft_id,
                          draft.subject AS draft_subject, draft.body AS draft_body,
                          draft.requested_changes_json
                   FROM document_comparisons dc
                   LEFT JOIN document_review_decisions drd ON drd.comparison_id = dc.id
                   LEFT JOIN document_revision_drafts draft ON draft.comparison_id = dc.id
                   WHERE dc.id = ?""", (comparison_id,)
            ).fetchone()
            return dict(row) if row else None

    def save_revision_draft(self, comparison_id: int, draft: RevisionRequestDraft):
        with self.connect() as connection:
            existing = connection.execute(
                "SELECT * FROM document_revision_drafts WHERE comparison_id = ?",
                (comparison_id,),
            ).fetchone()
            if existing:
                return dict(existing), True
            cursor = connection.execute(
                """INSERT INTO document_revision_drafts
                   (comparison_id, subject, body, requested_changes_json)
                   VALUES (?, ?, ?, ?)""",
                (comparison_id, draft.subject, draft.body, json.dumps(draft.requested_changes)),
            )
            connection.execute(
                """INSERT INTO audit_log (entity_type, entity_id, event, details_json)
                   VALUES ('document_comparison', ?, 'revision_draft_created', ?)""",
                (comparison_id, json.dumps({"draft_id": cursor.lastrowid})),
            )
            row = connection.execute(
                "SELECT * FROM document_revision_drafts WHERE id = ?", (cursor.lastrowid,)
            ).fetchone()
            return dict(row), False

    def list_revision_drafts(self):
        with self.connect() as connection:
            rows = connection.execute(
                """SELECT drd.*, dc.candidate_filename, dc.reference_filename,
                          delivery.id AS delivery_id, delivery.recipient,
                          delivery.status AS delivery_status,
                          delivery.provider_draft_id, delivery.error_message
                   FROM document_revision_drafts drd
                   JOIN document_comparisons dc ON dc.id = drd.comparison_id
                   LEFT JOIN revision_draft_deliveries delivery
                       ON delivery.revision_draft_id = drd.id
                   ORDER BY drd.created_at DESC"""
            ).fetchall()
            return [dict(row) for row in rows]

    def approve_revision_draft_delivery(self, draft_id: int, recipient: str, note: str):
        with self.connect() as connection:
            draft = connection.execute(
                "SELECT 1 FROM document_revision_drafts WHERE id = ?", (draft_id,)
            ).fetchone()
            if not draft:
                return None, "not_found"
            try:
                cursor = connection.execute(
                    """INSERT INTO revision_draft_deliveries
                       (revision_draft_id, recipient, approval_note)
                       VALUES (?, ?, ?)""", (draft_id, recipient.strip(), note.strip())
                )
            except sqlite3.IntegrityError:
                return None, "already_approved"
            connection.execute(
                """INSERT INTO audit_log (entity_type, entity_id, event, details_json)
                   VALUES ('revision_draft', ?, 'gmail_draft_approved', ?)""",
                (draft_id, json.dumps({"recipient": recipient.strip(), "note": note.strip()})),
            )
            row = connection.execute(
                "SELECT * FROM revision_draft_deliveries WHERE id = ?", (cursor.lastrowid,)
            ).fetchone()
            return dict(row), None

    def claim_revision_draft_delivery(self, delivery_id: int):
        with self.connect() as connection:
            cursor = connection.execute(
                """UPDATE revision_draft_deliveries SET status = 'executing'
                   WHERE id = ? AND status = 'approved'""", (delivery_id,)
            )
            if cursor.rowcount == 0:
                return None
            row = connection.execute(
                """SELECT delivery.*, draft.subject, draft.body
                   FROM revision_draft_deliveries delivery
                   JOIN document_revision_drafts draft ON draft.id = delivery.revision_draft_id
                   WHERE delivery.id = ?""", (delivery_id,)
            ).fetchone()
            return dict(row)

    def finish_revision_draft_delivery(self, delivery_id: int, provider_draft_id: str):
        with self.connect() as connection:
            connection.execute(
                """UPDATE revision_draft_deliveries
                   SET status = 'executed', provider_draft_id = ?, executed_at = CURRENT_TIMESTAMP
                   WHERE id = ? AND status = 'executing'""", (provider_draft_id, delivery_id)
            )
            connection.execute(
                """INSERT INTO audit_log (entity_type, entity_id, event, details_json)
                   VALUES ('revision_draft_delivery', ?, 'gmail_draft_created', ?)""",
                (delivery_id, json.dumps({"provider_draft_id": provider_draft_id})),
            )
            row = connection.execute(
                "SELECT * FROM revision_draft_deliveries WHERE id = ?", (delivery_id,)
            ).fetchone()
            return dict(row)

    def fail_revision_draft_delivery(self, delivery_id: int, error: str):
        with self.connect() as connection:
            connection.execute(
                """UPDATE revision_draft_deliveries SET status = 'failed', error_message = ?
                   WHERE id = ? AND status = 'executing'""", (error[:2000], delivery_id)
            )

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

    def add_entity_alias(self, entity_id: int, alias: str):
        normalized = normalize_entity_name(alias)
        if not normalized:
            raise ValueError("Alias must contain letters or numbers")
        with self.connect() as connection:
            target = connection.execute(
                "SELECT * FROM entities WHERE id = ?", (entity_id,)
            ).fetchone()
            if not target:
                raise ValueError("Target entity does not exist")
            conflicting_entity = connection.execute(
                "SELECT id, name FROM entities WHERE normalized_name = ?", (normalized,)
            ).fetchone()
            if conflicting_entity:
                if conflicting_entity["id"] == entity_id:
                    return {"entity_id": entity_id, "alias": alias, "already_resolves": True}
                raise ValueError(
                    f"Alias already belongs to entity '{conflicting_entity['name']}'"
                )
            existing_alias = connection.execute(
                """SELECT a.entity_id, e.name FROM entity_aliases a
                   JOIN entities e ON e.id = a.entity_id
                   WHERE a.normalized_alias = ?""", (normalized,)
            ).fetchone()
            if existing_alias:
                if existing_alias["entity_id"] == entity_id:
                    return {"entity_id": entity_id, "alias": alias, "already_resolves": True}
                raise ValueError(f"Alias already belongs to entity '{existing_alias['name']}'")
            connection.execute(
                """INSERT INTO entity_aliases (entity_id, alias, normalized_alias)
                   VALUES (?, ?, ?)""", (entity_id, alias.strip(), normalized)
            )
            connection.execute(
                "UPDATE entities SET updated_at = CURRENT_TIMESTAMP WHERE id = ?", (entity_id,)
            )
            connection.execute(
                """INSERT INTO audit_log (entity_type, entity_id, event, details_json)
                   VALUES ('entity', ?, 'alias_added', ?)""",
                (entity_id, json.dumps({"alias": alias.strip()})),
            )
            return {"entity_id": entity_id, "alias": alias.strip(), "already_resolves": False}

    def merge_entities(self, target_id: int, source_name_or_alias: str):
        with self.connect() as connection:
            target = connection.execute(
                "SELECT * FROM entities WHERE id = ?", (target_id,)
            ).fetchone()
            if not target:
                raise ValueError("Target entity does not exist")
            normalized_source = normalize_entity_name(source_name_or_alias)
            source = connection.execute(
                """SELECT DISTINCT e.* FROM entities e
                   LEFT JOIN entity_aliases a ON a.entity_id = e.id
                   WHERE e.normalized_name = ? OR a.normalized_alias = ?""",
                (normalized_source, normalized_source),
            ).fetchone()
            if not source:
                raise ValueError(f"Source entity '{source_name_or_alias}' does not exist")
            if source["id"] == target_id:
                raise ValueError("Source and target resolve to the same entity")

            source_aliases = connection.execute(
                "SELECT alias, normalized_alias FROM entity_aliases WHERE entity_id = ?",
                (source["id"],),
            ).fetchall()
            connection.execute(
                """INSERT OR IGNORE INTO email_entities (email_id, entity_id)
                   SELECT email_id, ? FROM email_entities WHERE entity_id = ?""",
                (target_id, source["id"]),
            )
            connection.execute("DELETE FROM email_entities WHERE entity_id = ?", (source["id"],))
            connection.execute(
                """INSERT OR IGNORE INTO calendar_event_entities (calendar_event_id, entity_id)
                   SELECT calendar_event_id, ? FROM calendar_event_entities WHERE entity_id = ?""",
                (target_id, source["id"]),
            )
            connection.execute(
                "DELETE FROM calendar_event_entities WHERE entity_id = ?", (source["id"],)
            )
            connection.execute(
                """INSERT OR IGNORE INTO document_entities (document_id, entity_id)
                   SELECT document_id, ? FROM document_entities WHERE entity_id = ?""",
                (target_id, source["id"]),
            )
            connection.execute("DELETE FROM document_entities WHERE entity_id = ?", (source["id"],))
            connection.execute(
                """INSERT OR IGNORE INTO document_comparison_entities (comparison_id, entity_id)
                   SELECT comparison_id, ? FROM document_comparison_entities WHERE entity_id = ?""",
                (target_id, source["id"]),
            )
            connection.execute(
                "DELETE FROM document_comparison_entities WHERE entity_id = ?", (source["id"],)
            )
            connection.execute(
                "UPDATE decisions SET entity_id = ? WHERE entity_id = ?", (target_id, source["id"])
            )
            connection.execute("DELETE FROM entity_aliases WHERE entity_id = ?", (source["id"],))
            aliases_to_move = [(source["name"], source["normalized_name"])] + [
                (row["alias"], row["normalized_alias"]) for row in source_aliases
            ]
            for alias, normalized_alias in aliases_to_move:
                connection.execute(
                    """INSERT OR IGNORE INTO entity_aliases
                       (entity_id, alias, normalized_alias) VALUES (?, ?, ?)""",
                    (target_id, alias, normalized_alias),
                )
            connection.execute("DELETE FROM entities WHERE id = ?", (source["id"],))
            connection.execute(
                "UPDATE entities SET updated_at = CURRENT_TIMESTAMP WHERE id = ?", (target_id,)
            )
            details = {
                "source_entity_id": source["id"],
                "source_entity_name": source["name"],
                "target_entity_name": target["name"],
            }
            connection.execute(
                """INSERT INTO audit_log (entity_type, entity_id, event, details_json)
                   VALUES ('entity', ?, 'merged', ?)""",
                (target_id, json.dumps(details)),
            )
            result = connection.execute(
                "SELECT * FROM entities WHERE id = ?", (target_id,)
            ).fetchone()
            return {"entity": dict(result), "merged": details}

    def list_open_commitments(self):
        with self.connect() as connection:
            rows = connection.execute(
                """SELECT c.*, e.subject AS source_subject,
                          GROUP_CONCAT(DISTINCT en.name) AS entity_names
                   FROM commitments c
                   JOIN emails e ON e.id = c.email_id
                   LEFT JOIN email_entities ee ON ee.email_id = e.id
                   LEFT JOIN entities en ON en.id = ee.entity_id
                   WHERE c.status = 'open'
                   GROUP BY c.id
                   ORDER BY c.deadline, c.id"""
            ).fetchall()
            return [dict(row) for row in rows]

    def create_open_loop_alert(self, commitment: dict, alert_type: str):
        deadline_snapshot = commitment.get("deadline") or "missing"
        with self.connect() as connection:
            existing = connection.execute(
                """SELECT a.* FROM open_loop_alerts ola
                   JOIN proposed_actions a ON a.id = ola.proposed_action_id
                   WHERE ola.commitment_id = ? AND ola.alert_type = ?
                         AND ola.deadline_snapshot = ?""",
                (commitment["id"], alert_type, deadline_snapshot),
            ).fetchone()
            if existing:
                return dict(existing), False
            label = "Overdue" if alert_type == "overdue" else "Due soon"
            entity = commitment.get("entity_names") or "unassigned entity"
            description = (
                f"{label} open loop for {entity}: {commitment['title']} "
                f"(deadline: {deadline_snapshot}). Review and choose the next action."
            )
            payload = {
                "monitor": "open_loop",
                "alert_type": alert_type,
                "deadline": commitment.get("deadline"),
                "entity_names": commitment.get("entity_names"),
            }
            cursor = connection.execute(
                """INSERT INTO proposed_actions
                   (commitment_id, email_id, action_type, description, payload_json, status)
                   VALUES (?, ?, 'open_loop_review', ?, ?, ?)""",
                (commitment["id"], commitment["email_id"], description,
                 json.dumps(payload), ActionStatus.PENDING_APPROVAL.value),
            )
            action_id = cursor.lastrowid
            connection.execute(
                """INSERT INTO open_loop_alerts
                   (commitment_id, alert_type, deadline_snapshot, proposed_action_id)
                   VALUES (?, ?, ?, ?)""",
                (commitment["id"], alert_type, deadline_snapshot, action_id),
            )
            connection.execute(
                """INSERT INTO audit_log (entity_type, entity_id, event, details_json)
                   VALUES ('commitment', ?, 'open_loop_alert_created', ?)""",
                (commitment["id"], json.dumps({"action_id": action_id, **payload})),
            )
            return dict(connection.execute(
                "SELECT * FROM proposed_actions WHERE id = ?", (action_id,)
            ).fetchone()), True

    def complete_commitment(self, commitment_id: int, note: str | None):
        with self.connect() as connection:
            cursor = connection.execute(
                """UPDATE commitments SET status = 'completed', completed_at = CURRENT_TIMESTAMP
                   WHERE id = ? AND status = 'open'""", (commitment_id,)
            )
            if cursor.rowcount == 0:
                return None
            connection.execute(
                """UPDATE proposed_actions
                   SET status = ?, decision_note = ?, decided_at = CURRENT_TIMESTAMP
                   WHERE commitment_id = ? AND action_type = 'open_loop_review'
                         AND status = ?""",
                (ActionStatus.REJECTED.value,
                 f"Closed automatically when commitment completed. {note or ''}".strip(),
                 commitment_id, ActionStatus.PENDING_APPROVAL.value),
            )
            connection.execute(
                """INSERT INTO audit_log (entity_type, entity_id, event, details_json)
                   VALUES ('commitment', ?, 'completed', ?)""",
                (commitment_id, json.dumps({"note": note})),
            )
            return dict(connection.execute(
                "SELECT * FROM commitments WHERE id = ?", (commitment_id,)
            ).fetchone())

    def match_entities(self, text: str):
        normalized_text = f" {normalize_entity_name(text)} "
        if not normalized_text.strip():
            return []
        with self.connect() as connection:
            rows = connection.execute(
                """SELECT e.id, e.name, e.normalized_name AS candidate FROM entities e
                   UNION ALL
                   SELECT e.id, e.name, a.normalized_alias AS candidate
                   FROM entity_aliases a JOIN entities e ON e.id = a.entity_id"""
            ).fetchall()
            matched = {}
            for row in rows:
                candidate = row["candidate"]
                if candidate and f" {candidate} " in normalized_text:
                    current = matched.get(row["id"])
                    if current is None or len(candidate) > len(current["matched_name"]):
                        matched[row["id"]] = {
                            "id": row["id"], "name": row["name"], "matched_name": candidate
                        }
            return sorted(matched.values(), key=lambda item: len(item["matched_name"]), reverse=True)

    def save_calendar_event(self, event: dict, entity_ids: list[int]):
        with self.connect() as connection:
            existing = connection.execute(
                """SELECT id FROM calendar_events
                   WHERE google_event_id = ? AND calendar_id = ?""",
                (event["google_event_id"], event["calendar_id"]),
            ).fetchone()
            values = (
                event["title"], event.get("description"), event.get("location"),
                event.get("start_at"), event.get("end_at"), int(event.get("all_day", False)),
                event.get("status", "confirmed"), event.get("attendees_json", "[]"),
                event.get("html_link"), event.get("meeting_link"), event.get("updated_at_source"),
            )
            if existing:
                event_id = existing["id"]
                connection.execute(
                    """UPDATE calendar_events SET title = ?, description = ?, location = ?,
                       start_at = ?, end_at = ?, all_day = ?, status = ?, attendees_json = ?,
                       html_link = ?, meeting_link = ?, updated_at_source = ?,
                       imported_at = CURRENT_TIMESTAMP WHERE id = ?""",
                    (*values, event_id),
                )
                created = False
            else:
                cursor = connection.execute(
                    """INSERT INTO calendar_events
                       (google_event_id, calendar_id, title, description, location,
                        start_at, end_at, all_day, status, attendees_json, html_link,
                        meeting_link, updated_at_source)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (event["google_event_id"], event["calendar_id"], *values),
                )
                event_id = cursor.lastrowid
                created = True
            connection.execute(
                "DELETE FROM calendar_event_entities WHERE calendar_event_id = ?", (event_id,)
            )
            for entity_id in entity_ids:
                connection.execute(
                    """INSERT OR IGNORE INTO calendar_event_entities
                       (calendar_event_id, entity_id) VALUES (?, ?)""", (event_id, entity_id)
                )
            connection.execute(
                """INSERT INTO audit_log (entity_type, entity_id, event, details_json)
                   VALUES ('calendar_event', ?, ?, ?)""",
                (event_id, "imported" if created else "updated",
                 json.dumps({"entity_ids": entity_ids, "google_event_id": event["google_event_id"]})),
            )
            row = connection.execute("SELECT * FROM calendar_events WHERE id = ?", (event_id,)).fetchone()
            return dict(row), created

    def list_calendar_events(self):
        with self.connect() as connection:
            rows = connection.execute(
                """SELECT ce.*, GROUP_CONCAT(DISTINCT e.name) AS entity_names
                   FROM calendar_events ce
                   LEFT JOIN calendar_event_entities cee ON cee.calendar_event_id = ce.id
                   LEFT JOIN entities e ON e.id = cee.entity_id
                   GROUP BY ce.id ORDER BY ce.start_at"""
            ).fetchall()
            return [dict(row) for row in rows]

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
            calendar_events = connection.execute(
                """SELECT ce.id, ce.title, ce.location, ce.start_at, ce.end_at, ce.all_day,
                          ce.status, ce.attendees_json, ce.meeting_link, ce.html_link
                   FROM calendar_events ce
                   JOIN calendar_event_entities cee ON cee.calendar_event_id = ce.id
                   WHERE cee.entity_id = ? ORDER BY ce.start_at DESC""", (entity_id,)
            ).fetchall()
            documents = connection.execute(
                """SELECT d.id, d.filename, d.document_type, d.summary,
                          d.analysis_json, d.created_at
                   FROM documents d JOIN document_entities de ON de.document_id = d.id
                   WHERE de.entity_id = ? ORDER BY d.created_at DESC""", (entity_id,)
            ).fetchall()
            document_comparisons = connection.execute(
                """SELECT dc.id, dc.candidate_filename, dc.reference_filename,
                          dc.executive_summary, dc.comparison_json, dc.created_at,
                          COALESCE(drd.decision, 'pending_review') AS review_status,
                          drd.note AS review_note, drd.decided_at
                   FROM document_comparisons dc
                   JOIN document_comparison_entities dce ON dce.comparison_id = dc.id
                   LEFT JOIN document_review_decisions drd ON drd.comparison_id = dc.id
                   WHERE dce.entity_id = ? ORDER BY dc.created_at DESC""", (entity_id,)
            ).fetchall()
            return {
                "entity": dict(entity),
                "emails": [dict(row) for row in emails],
                "commitments": [dict(row) for row in commitments],
                "actions": [dict(row) for row in actions],
                "decisions": [dict(row) for row in decisions],
                "calendar_events": [dict(row) for row in calendar_events],
                "documents": [dict(row) for row in documents],
                "document_comparisons": [dict(row) for row in document_comparisons],
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
        for calendar_event in context["calendar_events"]:
            events.append({"type": "calendar_event", "timestamp": calendar_event["start_at"],
                           "data": calendar_event})
        for document in context["documents"]:
            events.append({"type": "document", "timestamp": document["created_at"],
                           "data": document})
        for comparison in context["document_comparisons"]:
            events.append({"type": "document_comparison", "timestamp": comparison["created_at"],
                           "data": comparison})
        events.sort(key=lambda event: event["timestamp"] or "", reverse=True)
        return {"entity": context["entity"], "events": events}
