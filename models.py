from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field


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
    open_commitments: list[str] = Field(default_factory=list)
    pending_actions: list[str] = Field(default_factory=list)
    decisions: list[str] = Field(default_factory=list)
    blockers: list[str] = Field(default_factory=list)
    recommended_next_action: str
    missing_information: list[str] = Field(default_factory=list)
