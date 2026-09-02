from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field, field_validator


def normalize_confidence(value):
    if isinstance(value, str):
        label = value.strip().casefold()
        labels = {"low": 0.25, "medium": 0.5, "high": 0.85}
        if label in labels:
            return labels[label]
        try:
            return float(label)
        except ValueError:
            return 0.5
    return value


class ActionStatus(str, Enum):
    PENDING_APPROVAL = "pending_approval"
    APPROVED = "approved"
    EXECUTING = "executing"
    REJECTED = "rejected"
    EXECUTED = "executed"
    FAILED = "failed"


class EmailRequest(BaseModel):
    subject: str = Field(min_length=1, max_length=500)
    body: str = Field(min_length=1)
    sender: str | None = None
    gmail_msg_id: str | None = None


class EmailAnalysis(BaseModel):
    category: Literal["information", "task", "meeting", "decision", "follow_up", "other"]
    summary: str
    contact_name: str | None = None
    company_or_project: str | None = None
    commitment_title: str | None = None
    deadline: str | None = None
    urgency: Literal["low", "medium", "high"] = "medium"
    proposed_action: str | None = None
    suggested_reply: str | None = None
    requires_approval: bool = True
    confidence: float = Field(default=0.5, ge=0, le=1)


class AnalysisResult(BaseModel):
    email_id: int
    analysis: EmailAnalysis
    commitment_id: int | None = None
    action_id: int | None = None


class DecisionRequest(BaseModel):
    note: str | None = Field(default=None, max_length=1000)


class GmailImportRequest(BaseModel):
    label: str = Field(default="AI-Operator", min_length=1, max_length=100)
    max_results: int = Field(default=10, ge=1, le=50)


class GmailAttachmentImportRequest(BaseModel):
    label: str = Field(default="AI-Operator", min_length=1, max_length=100)
    max_messages: int = Field(default=10, ge=1, le=50)


class RecordDecisionRequest(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    decision: str = Field(min_length=1, max_length=5000)
    rationale: str | None = Field(default=None, max_length=5000)
    status: Literal["proposed", "final", "reversed"] = "final"
    source_email_id: int | None = None


class EntityStatusBrief(BaseModel):
    entity: str
    current_status: str
    recent_activity: list[str] = Field(default_factory=list)
    upcoming_meetings: list[str] = Field(default_factory=list)
    open_commitments: list[str] = Field(default_factory=list)
    pending_actions: list[str] = Field(default_factory=list)
    decisions: list[str] = Field(default_factory=list)
    blockers: list[str] = Field(default_factory=list)
    recommended_next_action: str
    missing_information: list[str] = Field(default_factory=list)


class EntityAliasRequest(BaseModel):
    alias: str = Field(min_length=1, max_length=300)


class EntityMergeRequest(BaseModel):
    source_entity: str = Field(min_length=1, max_length=300)


class OpenLoopMonitorRequest(BaseModel):
    due_within_days: int = Field(default=3, ge=0, le=30)


class CompleteCommitmentRequest(BaseModel):
    note: str | None = Field(default=None, max_length=2000)


class CalendarImportRequest(BaseModel):
    calendar_id: str = Field(default="primary", min_length=1, max_length=300)
    days_before: int = Field(default=30, ge=0, le=365)
    days_after: int = Field(default=90, ge=1, le=365)


class DocumentAnalysis(BaseModel):
    document_type: Literal["contract", "proposal", "report", "invoice", "other"]
    summary: str
    company_or_project: str | None = None
    parties: list[str] = Field(default_factory=list)
    obligations: list[str] = Field(default_factory=list)
    deadlines: list[str] = Field(default_factory=list)
    financial_terms: list[str] = Field(default_factory=list)
    risk_indicators: list[str] = Field(default_factory=list)
    missing_information: list[str] = Field(default_factory=list)
    recommendation: Literal["review", "revise", "approve", "reject"] = "review"
    recommendation_reason: str
    confidence: float = Field(default=0.5, ge=0, le=1)

    _normalize_confidence = field_validator("confidence", mode="before")(normalize_confidence)


class DocumentAnalysisResult(BaseModel):
    document_id: int
    filename: str
    analysis: DocumentAnalysis
    entity_id: int | None = None
    duplicate: bool = False
    disclaimer: str = "AI review aid only; not legal advice. Human review is required."


class MaterialDifference(BaseModel):
    topic: str
    reference_position: str
    candidate_position: str
    significance: Literal["low", "medium", "high"]
    impact: str
    suggested_resolution: str


class DocumentComparison(BaseModel):
    company_or_project: str | None = None
    executive_summary: str
    material_differences: list[MaterialDifference] = Field(default_factory=list)
    added_terms: list[str] = Field(default_factory=list)
    removed_terms: list[str] = Field(default_factory=list)
    unchanged_key_terms: list[str] = Field(default_factory=list)
    missing_information: list[str] = Field(default_factory=list)
    recommendation: Literal["review", "revise", "approve", "reject"] = "review"
    recommendation_reason: str
    confidence: float = Field(default=0.5, ge=0, le=1)

    _normalize_confidence = field_validator("confidence", mode="before")(normalize_confidence)


class DocumentComparisonResult(BaseModel):
    comparison_id: int
    candidate_filename: str
    reference_filename: str
    comparison: DocumentComparison
    entity_id: int | None = None
    duplicate: bool = False
    disclaimer: str = "AI comparison aid only; not legal advice. Human review is required."


class DocumentReviewDecisionRequest(BaseModel):
    decision: Literal["approved", "revision_requested", "rejected"]
    note: str = Field(min_length=1, max_length=2000)


class RevisionRequestDraft(BaseModel):
    subject: str = Field(min_length=1, max_length=300)
    body: str = Field(min_length=1, max_length=10_000)
    requested_changes: list[str] = Field(default_factory=list)


class RevisionRequestDraftResult(BaseModel):
    draft_id: int
    comparison_id: int
    draft: RevisionRequestDraft
    duplicate: bool = False
    external_action_taken: bool = False


class RevisionDraftApprovalRequest(BaseModel):
    recipient: str = Field(
        min_length=5, max_length=320,
        pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$",
    )
    note: str = Field(min_length=1, max_length=2000)


class TrustedReferenceRequest(BaseModel):
    label: str = Field(min_length=1, max_length=300)
    note: str = Field(min_length=1, max_length=2000)


class ContractAutomationScheduleRequest(BaseModel):
    enabled: bool = False
    interval_minutes: int = Field(default=15, ge=1, le=1440)
    label: str = Field(default="AI-Operator", min_length=1, max_length=100)
    max_messages: int = Field(default=10, ge=1, le=50)
