import json
import hmac
import html
import os
from datetime import datetime, timedelta
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, File, Header, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

from analyzer import EmailAnalyzer
from automation_scheduler import AutomationScheduler
from calendar_auth import get_calendar_service
from calendar_operator import CalendarOperator
from contract_automation import ContractIntakeAutomation
from database import Database
from document_processor import extract_document
from gmail_auth import get_gmail_service
from gmail_operator import GmailOperator, action_reply_subject, action_reply_text
from inbox_automation import InboxAutomation
from n8n_operator import N8nDispatchError, dispatch_candidate_result, dispatch_operational_record
from models import (
    ActionStatus,
    AnalysisResult,
    DecisionRequest,
    EmailRequest,
    GmailImportRequest,
    GmailAttachmentImportRequest,
    RecordDecisionRequest,
    EntityStatusBrief,
    EntityAliasRequest,
    EntityMergeRequest,
    OpenLoopMonitorRequest,
    CompleteCommitmentRequest,
    CalendarImportRequest,
    DocumentAnalysisResult,
    DocumentComparison,
    DocumentComparisonResult,
    DocumentReviewDecisionRequest,
    RevisionRequestDraft,
    RevisionRequestDraftResult,
    RevisionDraftApprovalRequest,
    TrustedReferenceRequest,
    ContractAutomationScheduleRequest,
    ExecutiveBriefing,
    OperatorQuestion,
    OperatorAnswer,
    OperatorPlanResult,
    InboxAutomationScheduleRequest,
    ActionDraftUpdateRequest,
    CalendarEventProposalUpdateRequest,
    DecisionProposalUpdateRequest,
    FollowUpProposalUpdateRequest,
    OperationalRecordProposal,
    CandidateReviewDecisionRequest,
    CandidateInterviewPackageUpdateRequest,
    CandidateOnboardingPackageUpdateRequest,
    TrelloCandidateStatusRequest,
)
from open_loops import OpenLoopMonitor
from follow_ups import FollowUpMonitor, normalize_follow_up_time

load_dotenv()

database = Database(os.getenv("DATABASE_PATH", "operator.db"))
app = FastAPI(title="AI Commitment Operator", version="0.41.0-dev")
static_directory = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=static_directory), name="static")


def _execute_contract_intake(label: str, max_messages: int, trigger: str):
    run_id = database.start_automation_run("contract_intake")
    try:
        attachments = GmailOperator(get_gmail_service()).list_labeled_attachments(
            label, max_messages
        )
        result = ContractIntakeAutomation(database, EmailAnalyzer()).run(attachments)
        result.update({"run_id": run_id, "trigger": trigger})
        database.finish_automation_run(run_id, result)
        return result
    except Exception as exc:
        database.fail_automation_run(run_id, str(exc))
        raise


def _execute_inbox_automation(label: str, max_results: int, trigger: str):
    run_id = database.start_automation_run("inbox_automation")
    try:
        gmail = GmailOperator(get_gmail_service())
        analyzer = EmailAnalyzer()
        emails = gmail.list_labeled_emails(label, max_results)
        attachments = gmail.list_labeled_attachments(label, max_results)
        result = InboxAutomation(
            database, analyzer, ContractIntakeAutomation(database, analyzer)
        ).run(emails, attachments=attachments)
        result.update({"run_id": run_id, "trigger": trigger})
        database.finish_automation_run(run_id, result)
        return result
    except Exception as exc:
        database.fail_automation_run(run_id, str(exc))
        raise


scheduler = AutomationScheduler(database, _execute_contract_intake, _execute_inbox_automation)


@app.on_event("startup")
def startup_event():
    database.init()
    scheduler.start()


@app.on_event("shutdown")
def shutdown_event():
    scheduler.stop()


@app.get("/health")
def health():
    return {
        "status": "ok",
        "gmail_polling_enabled": False,
        "gmail_manual_import_enabled": True,
        "inbox_automation_enabled": True,
        "multi_scenario_email_recognition_enabled": True,
        "inbox_attachment_routing_enabled": True,
        "inbox_automation_scheduler_configured": bool(database.get_inbox_schedule()["enabled"]),
        "gmail_attachment_import_enabled": True,
        "trusted_reference_library_enabled": True,
        "contract_intake_automation_enabled": True,
        "contract_intake_scheduler_configured": bool(database.get_contract_schedule()["enabled"]),
        "automatic_sending_enabled": False,
        "calendar_manual_import_enabled": True,
        "calendar_writes_enabled": True,
        "calendar_write_requires_action_approval": True,
        "candidate_calendar_availability_enabled": True,
        "candidate_trello_completion_sync_enabled": True,
        "candidate_onboarding_enabled": True,
        "contract_draft_requires_hr_legal_review": True,
        "document_analysis_enabled": True,
        "document_signing_enabled": False,
        "document_comparison_enabled": True,
        "document_evidence_verification_enabled": True,
        "prioritized_human_review_queue_enabled": True,
        "grounded_executive_briefing_enabled": True,
        "grounded_operator_questions_enabled": True,
        "approval_gated_operator_plans_enabled": True,
        "document_human_review_required": True,
        "revision_draft_enabled": True,
        "revision_gmail_draft_enabled": True,
    }


@app.get("/dashboard", include_in_schema=False)
def dashboard():
    return FileResponse(static_directory / "dashboard.html")


@app.post("/analyze-email", response_model=AnalysisResult)
def analyze_email(email: EmailRequest):
    try:
        analysis = EmailAnalyzer().analyze(email)
        email_id, commitment_id, action_id = database.save_analysis(email, analysis)
        return AnalysisResult(
            email_id=email_id,
            analysis=analysis,
            commitment_id=commitment_id,
            action_id=action_id,
        )
    except Exception as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/process-email", response_model=AnalysisResult, deprecated=True)
def process_email(email: EmailRequest):
    """Backward-compatible alias for the original demo endpoint."""
    return analyze_email(email)


@app.get("/commitments")
def list_commitments(status: str | None = Query(default=None)):
    return {"commitments": database.list_rows("commitments", status)}


@app.post("/commitments/{commitment_id}/complete")
def complete_commitment(commitment_id: int, request: CompleteCommitmentRequest):
    commitment = database.complete_commitment(commitment_id, request.note)
    if commitment is None:
        raise HTTPException(status_code=409, detail="Commitment does not exist or is not open")
    return commitment


@app.get("/actions")
def list_actions(status: str | None = Query(default=None)):
    return {"actions": database.list_rows("proposed_actions", status)}


def _decide(action_id: int, status: ActionStatus, decision: DecisionRequest):
    action = database.decide_action(action_id, status, decision.note)
    if action is None:
        raise HTTPException(
            status_code=409,
            detail="Action does not exist or is no longer pending approval",
        )
    return action


@app.post("/actions/{action_id}/approve")
def approve_action(action_id: int, decision: DecisionRequest):
    return _decide(action_id, ActionStatus.APPROVED, decision)


@app.post("/actions/{action_id}/reject")
def reject_action(action_id: int, decision: DecisionRequest):
    return _decide(action_id, ActionStatus.REJECTED, decision)


@app.put("/actions/{action_id}/draft")
def update_action_draft(action_id: int, request: ActionDraftUpdateRequest):
    action = database.update_action_payload(
        action_id, {"draft_subject": request.subject, "suggested_reply": request.body},
        {"draft_reply"},
    )
    if action is None:
        raise HTTPException(status_code=409, detail="Editable draft action was not found")
    return action


@app.put("/actions/{action_id}/calendar-proposal")
def update_calendar_proposal(action_id: int, request: CalendarEventProposalUpdateRequest):
    action = database.update_action_payload(
        action_id, {"calendar_event": request.model_dump()}, {"calendar_event"},
        allow_failed_retry=True,
    )
    if action is None:
        raise HTTPException(status_code=409, detail="Editable Calendar proposal was not found")
    return action


@app.put("/actions/{action_id}/candidate-interview-package")
def update_candidate_interview_package(
    action_id: int, request: CandidateInterviewPackageUpdateRequest
):
    action = database.update_action_payload(
        action_id,
        {
            "calendar_event": request.calendar_event.model_dump(),
            "draft_subject": request.email_subject,
            "suggested_reply": request.email_body,
        },
        {"candidate_interview_package"},
        allow_failed_retry=True,
    )
    if action is None:
        raise HTTPException(status_code=409, detail="Editable interview package was not found")
    return action


@app.put("/actions/{action_id}/candidate-onboarding-package")
def update_candidate_onboarding_package(
    action_id: int, request: CandidateOnboardingPackageUpdateRequest
):
    action = database.update_action_payload(
        action_id, {"onboarding": request.model_dump()}, {"create_onboarding_package"},
        allow_failed_retry=True,
    )
    if action is None:
        raise HTTPException(status_code=409, detail="Editable onboarding package was not found")
    return action


def build_contract_draft(proposal: CandidateOnboardingPackageUpdateRequest) -> str:
    employment_type = proposal.employment_type.replace("_", " ").title()
    return f"""DRAFT — FOR HR AND LEGAL REVIEW ONLY

EMPLOYMENT AGREEMENT

1. PARTIES

Employer: {proposal.legal_entity} (the “Employer”)
Employee: {proposal.employee_name} (the “Employee”)
Employee contact: {proposal.personal_email}

2. APPOINTMENT

The Employer intends to appoint the Employee as {proposal.job_title}, reporting
to {proposal.manager or '[manager to be confirmed]'}. The intended start date is
{proposal.start_date} and the proposed employment type is {employment_type}.

3. WORKING ARRANGEMENTS

Normal working time: {proposal.hours_per_week:g} hours per week
Primary work location: {proposal.work_location or '[work location to be confirmed]'}

4. TERMS TO BE COMPLETED BY HR AND LEGAL

- Salary, payment frequency and benefits
- Probation period and termination provisions
- Holiday, leave and absence arrangements
- Confidentiality, data protection and intellectual-property provisions
- Governing law, applicable collective agreements and mandatory local clauses

5. REVIEW AND SIGNATURE

This draft records the approved hiring and onboarding details only. It does not
create an employment relationship and must not be offered for signature until
authorised HR and legal reviewers have completed and approved every required term.

For the Employer: ____________________    Date: _______________

Employee: ____________________________    Date: _______________

AUTOMATION STATUS: No signature requested. Nothing has been sent to the candidate.
"""


@app.get("/actions/{action_id}/interview-slots")
def suggest_candidate_interview_slots(action_id: int):
    action = database.get_action_context(action_id)
    if not action or action["action_type"] != "candidate_interview_package":
        raise HTTPException(status_code=404, detail="Interview action was not found")
    if action["status"] not in {"pending_approval", "approved", "failed"}:
        raise HTTPException(status_code=409, detail="Interview action is already handled")
    analysis = json.loads(action.get("analysis_json") or "{}")
    if os.getenv("SAFE_DEMO_MODE", "false").strip().casefold() in {"1", "true", "yes", "on"}:
        payload = json.loads(action.get("payload_json") or "{}")
        proposed_start = (payload.get("calendar_event") or {}).get("start_at")
        start = datetime.fromisoformat(proposed_start) if proposed_start else (
            datetime.now().astimezone() + timedelta(days=1)
        ).replace(hour=10, minute=0, second=0, microsecond=0)
        slots = []
        for offset in range(3):
            slot_start = start + timedelta(days=offset)
            slot_end = slot_start + timedelta(minutes=30)
            slots.append({
                "start_at": slot_start.isoformat(),
                "end_at": slot_end.isoformat(),
                "label": slot_start.strftime("%a %d %b, %H:%M"),
                "preference_match": offset == 0,
                "reason": "Fictional demo availability",
            })
        return {"action_id": action_id, "duration_minutes": 30, "slots": slots}
    preference_text = " ".join(filter(None, [
        action.get("subject"), action.get("body"), analysis.get("summary"),
        analysis.get("availability_preferences"), analysis.get("proposed_action"),
    ]))
    try:
        slots = CalendarOperator(get_calendar_service()).suggest_interview_slots(
            preference_text=preference_text, count=3
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Calendar availability check failed: {exc}") from exc
    return {"action_id": action_id, "duration_minutes": 30, "slots": slots}


@app.put("/actions/{action_id}/decision-proposal")
def update_decision_proposal(action_id: int, request: DecisionProposalUpdateRequest):
    action = database.update_action_payload(
        action_id, {"decision_record": request.model_dump()}, {"record_decision"},
    )
    if action is None:
        raise HTTPException(status_code=409, detail="Editable decision proposal was not found")
    return action


@app.put("/actions/{action_id}/follow-up-proposal")
def update_follow_up_proposal(action_id: int, request: FollowUpProposalUpdateRequest):
    try:
        proposal = request.model_dump()
        proposal["follow_up_at"] = normalize_follow_up_time(request.follow_up_at)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="Follow-up time must be valid ISO-8601") from exc
    action = database.update_action_payload(
        action_id, {"follow_up": proposal}, {"schedule_follow_up"},
    )
    if action is None:
        raise HTTPException(status_code=409, detail="Editable follow-up proposal was not found")
    return action


@app.put("/actions/{action_id}/operational-record")
def update_operational_record_proposal(action_id: int, request: OperationalRecordProposal):
    action = database.update_action_payload(
        action_id, {"operational_record": request.model_dump()}, {"create_operational_record"},
    )
    if action is None:
        raise HTTPException(status_code=409, detail="Editable operational proposal was not found")
    return action


@app.post("/gmail/import")
def import_from_gmail(request: GmailImportRequest):
    """Analyze labeled mail without changing labels, read state, or message content."""
    try:
        gmail = GmailOperator(get_gmail_service())
        emails = gmail.list_labeled_emails(request.label, request.max_results)
        result = {"found": len(emails), "processed": [], "skipped": [], "errors": []}
        analyzer = EmailAnalyzer()
        for email in emails:
            if email.gmail_msg_id and database.email_exists(email.gmail_msg_id):
                result["skipped"].append(email.gmail_msg_id)
                continue
            try:
                analysis = analyzer.analyze(email)
                email_id, commitment_id, action_id = database.save_analysis(email, analysis)
                result["processed"].append({
                    "gmail_msg_id": email.gmail_msg_id,
                    "email_id": email_id,
                    "commitment_id": commitment_id,
                    "action_id": action_id,
                })
            except Exception as exc:
                result["errors"].append({
                    "gmail_msg_id": email.gmail_msg_id, "error": str(exc)
                })
        return result
    except Exception as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/automation/inbox")
def run_inbox_automation(request: GmailImportRequest):
    """Analyze labeled mail and monitor open loops in one audited, read-only run."""
    try:
        return _execute_inbox_automation(request.label, request.max_results, "manual")
    except Exception as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


def _n8n_shared_secret():
    secret = os.getenv("N8N_SHARED_SECRET") or os.getenv("N8N_TRELLO_WEBHOOK_SECRET")
    if secret:
        return secret
    local_environment = Path(__file__).parent / ".env.n8n"
    if local_environment.exists():
        for line in local_environment.read_text(encoding="utf-8-sig").splitlines():
            if line.startswith("AI_OPERATOR_WEBHOOK_SECRET="):
                return line.split("=", 1)[1].strip()
    return ""


def _require_n8n_secret(supplied_secret: str | None):
    expected_secret = _n8n_shared_secret()
    if not expected_secret:
        raise HTTPException(status_code=503, detail="The n8n integration is not configured")
    if not supplied_secret or not hmac.compare_digest(supplied_secret, expected_secret):
        raise HTTPException(status_code=401, detail="Invalid n8n integration secret")


@app.post("/integrations/n8n/inbox-scan")
def run_n8n_inbox_automation(
    request: GmailImportRequest,
    x_ai_operator_secret: str | None = Header(default=None),
):
    """Allow authenticated n8n schedules to start the read-only inbox pipeline."""
    _require_n8n_secret(x_ai_operator_secret)
    try:
        # Scheduled scans inspect the full bounded window so a new labeled message
        # cannot be hidden behind ten already-processed messages.
        result = _execute_inbox_automation(request.label, max(request.max_results, 50), "n8n")
        result["new_work_count"] = len(result["processed"])
        result["requires_human_review"] = bool(
            result["processed"]
            or result["follow_up_monitor"]["created"]
            or result["open_loop_monitor"]["created"]
            or result.get("document_automation", {}).get("review_ready")
        )
        result["external_action_taken"] = False
        return result
    except Exception as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.get("/automation/inbox/schedule")
def get_inbox_automation_schedule():
    return database.get_inbox_schedule()


@app.put("/automation/inbox/schedule")
def configure_inbox_automation_schedule(request: InboxAutomationScheduleRequest):
    return database.configure_inbox_schedule(
        request.enabled, request.interval_minutes, request.label, request.max_results
    )


@app.post("/gmail/import-attachments")
def import_attachments_from_gmail(request: GmailAttachmentImportRequest):
    """Import supported attachments from labeled messages without modifying Gmail."""
    try:
        attachments = GmailOperator(get_gmail_service()).list_labeled_attachments(
            request.label, request.max_messages
        )
        result = {"found": len(attachments), "processed": [], "skipped": [], "errors": []}
        analyzer = EmailAnalyzer()
        for attachment in attachments:
            key = {
                "gmail_msg_id": attachment["gmail_msg_id"],
                "attachment_id": attachment["attachment_id"],
                "filename": attachment["filename"],
            }
            if database.gmail_attachment_import_exists(
                attachment["gmail_msg_id"], attachment["attachment_id"]
            ):
                result["skipped"].append({**key, "reason": "already_imported"})
                continue
            try:
                text, sha256 = extract_document(attachment["filename"], attachment["data"])
                existing = database.get_document_by_sha256(sha256)
                if existing:
                    document_id = existing["id"]
                    duplicate_document = True
                else:
                    analysis = analyzer.analyze_document(attachment["filename"], text)
                    stored, _, _ = database.save_document(
                        attachment["filename"], attachment.get("mime_type"), sha256, text, analysis
                    )
                    document_id = stored["id"]
                    duplicate_document = False
                database.link_gmail_attachment(document_id, attachment)
                result["processed"].append({
                    **key, "document_id": document_id,
                    "duplicate_document": duplicate_document,
                })
            except Exception as exc:
                result["errors"].append({**key, "error": str(exc)})
        return result
    except Exception as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/automation/contract-intake")
def run_contract_intake_automation(request: GmailAttachmentImportRequest):
    """Prepare labeled Gmail documents for human review in one controlled run."""
    try:
        return _execute_contract_intake(request.label, request.max_messages, "manual")
    except Exception as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.get("/automation/runs")
def list_automation_runs():
    return {"runs": database.list_automation_runs()}


@app.get("/automation/review-queue")
def get_automation_review_queue():
    return {"items": database.document_review_queue()}


@app.get("/automation/work-queue")
def get_automation_work_queue():
    return {"groups": database.list_work_queue()}


@app.post("/automation/executive-briefing", response_model=ExecutiveBriefing)
def generate_executive_briefing():
    try:
        briefing = EmailAnalyzer().create_executive_briefing(
            database.executive_briefing_context()
        )
        database.save_executive_briefing(briefing)
        return briefing
    except Exception as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.get("/automation/executive-briefings")
def list_executive_briefings():
    return {"briefings": database.list_executive_briefings()}


@app.post("/operator/ask", response_model=OperatorAnswer)
def ask_operator(request: OperatorQuestion):
    try:
        context = database.operator_question_context(request.question)
        return EmailAnalyzer().answer_operator_question(request.question, context)
    except Exception as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/operator/plans", response_model=OperatorPlanResult)
def create_operator_plan(request: OperatorQuestion):
    try:
        context = database.operator_question_context(request.question)
        plan = EmailAnalyzer().create_operator_plan(request.question, context)
        saved = database.save_operator_plan(plan)
        return OperatorPlanResult(plan_id=saved["id"], status=saved["status"], plan=plan)
    except Exception as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.get("/operator/plans")
def list_operator_plans():
    plans = database.list_operator_plans()
    for plan in plans:
        plan["plan"] = json.loads(plan.pop("plan_json"))
    return {"plans": plans}


def _decide_operator_plan(plan_id: int, status: str, decision: DecisionRequest):
    plan = database.decide_operator_plan(plan_id, status, decision.note)
    if plan is None:
        raise HTTPException(status_code=409, detail="Plan does not exist or is no longer pending")
    plan["plan"] = json.loads(plan.pop("plan_json"))
    plan["external_action_taken"] = False
    return plan


@app.post("/operator/plans/{plan_id}/approve")
def approve_operator_plan(plan_id: int, decision: DecisionRequest):
    return _decide_operator_plan(plan_id, "approved", decision)


@app.post("/operator/plans/{plan_id}/reject")
def reject_operator_plan(plan_id: int, decision: DecisionRequest):
    return _decide_operator_plan(plan_id, "rejected", decision)


@app.get("/automation/contract-intake/schedule")
def get_contract_intake_schedule():
    return database.get_contract_schedule()


@app.put("/automation/contract-intake/schedule")
def configure_contract_intake_schedule(request: ContractAutomationScheduleRequest):
    return database.configure_contract_schedule(
        request.enabled, request.interval_minutes, request.label, request.max_messages
    )


@app.post("/calendar/import")
def import_from_calendar(request: CalendarImportRequest):
    """Import a bounded event window without changing Google Calendar."""
    try:
        events = CalendarOperator(get_calendar_service()).list_events(
            calendar_id=request.calendar_id,
            days_before=request.days_before,
            days_after=request.days_after,
        )
        result = {"found": len(events), "created": [], "updated": [], "unmatched": []}
        for event in events:
            searchable_text = " ".join(filter(None, [
                event.get("title"), event.get("description"), event.get("location")
            ]))
            matches = database.match_entities(searchable_text)
            saved, created = database.save_calendar_event(
                event, [match["id"] for match in matches]
            )
            item = {
                "calendar_event_id": saved["id"],
                "google_event_id": event["google_event_id"],
                "title": event["title"],
                "entities": [match["name"] for match in matches],
            }
            result["created" if created else "updated"].append(item)
            if not matches:
                result["unmatched"].append(saved["id"])
        return result
    except Exception as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.get("/calendar/events")
def list_calendar_events():
    return {"events": database.list_calendar_events()}


@app.post("/documents/analyze", response_model=DocumentAnalysisResult)
async def analyze_document(file: UploadFile = File(...)):
    """Extract and analyze one local document without editing or transmitting it."""
    try:
        data = await file.read()
        text, sha256 = extract_document(file.filename or "", data)
        analysis = EmailAnalyzer().analyze_document(file.filename or "document", text)
        stored, entity_id, duplicate = database.save_document(
            file.filename or "document", file.content_type, sha256, text, analysis
        )
        if duplicate:
            analysis = type(analysis).model_validate_json(stored["analysis_json"])
        return DocumentAnalysisResult(
            document_id=stored["id"], filename=stored["filename"], analysis=analysis,
            entity_id=entity_id, duplicate=duplicate,
        )
    except Exception as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.get("/documents")
def list_documents():
    return {"documents": database.list_documents()}


@app.post("/documents/{document_id}/trusted-reference")
def mark_document_as_trusted_reference(document_id: int, request: TrustedReferenceRequest):
    reference, error = database.add_trusted_reference(document_id, request.label, request.note)
    if error == "not_found":
        raise HTTPException(status_code=404, detail="Document was not found")
    if error == "already_trusted":
        raise HTTPException(status_code=409, detail="Document is already a trusted reference")
    return {
        "trusted_reference": reference,
        "message": "Human-designated reference stored. AI did not assign trust.",
    }


@app.get("/documents/trusted-references")
def list_trusted_references():
    return {"trusted_references": database.list_trusted_references()}


@app.post("/documents/{document_id}/compare-with-trusted-reference")
def compare_with_trusted_reference(document_id: int):
    candidate, reference, error = database.select_trusted_reference(document_id)
    if error == "not_found":
        raise HTTPException(status_code=404, detail="Candidate document was not found")
    if error == "no_match":
        raise HTTPException(
            status_code=409,
            detail="No active trusted reference matches this entity and document type",
        )
    try:
        stored = database.get_document_comparison_by_hashes(
            candidate["sha256"], reference["sha256"]
        )
        if stored:
            comparison = DocumentComparison.model_validate_json(stored["comparison_json"])
            entity_id = candidate["entity_id"]
            duplicate = True
        else:
            comparison = EmailAnalyzer().compare_documents(
                candidate["filename"], candidate["extracted_text"],
                reference["filename"], reference["extracted_text"],
            )
            stored, entity_id, duplicate = database.save_document_comparison(
                candidate["filename"], candidate["sha256"],
                reference["filename"], reference["sha256"], comparison,
            )
        database.link_comparison_sources(stored["id"], candidate["id"], reference["id"])
        if duplicate:
            comparison = type(comparison).model_validate_json(stored["comparison_json"])
        return {
            "comparison_id": stored["id"],
            "candidate_document_id": candidate["id"],
            "trusted_reference_id": reference["trusted_reference_id"],
            "reference_document_id": reference["id"],
            "reference_label": reference["label"],
            "selection_reason": "same entity and document type" if reference["reference_entity_id"]
                                == candidate["entity_id"] else "global document-type reference",
            "comparison": comparison,
            "entity_id": entity_id,
            "duplicate": duplicate,
        }
    except Exception as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/documents/compare", response_model=DocumentComparisonResult)
async def compare_documents(candidate: UploadFile = File(...), reference: UploadFile = File(...)):
    """Compare a candidate document with a trusted reference; no external action is taken."""
    try:
        candidate_text, candidate_hash = extract_document(
            candidate.filename or "candidate", await candidate.read()
        )
        reference_text, reference_hash = extract_document(
            reference.filename or "reference", await reference.read()
        )
        stored = database.get_document_comparison_by_hashes(candidate_hash, reference_hash)
        if stored:
            comparison = DocumentComparison.model_validate_json(stored["comparison_json"])
            entity_id = stored.get("linked_entity_id")
            duplicate = True
        else:
            comparison = EmailAnalyzer().compare_documents(
                candidate.filename or "candidate", candidate_text,
                reference.filename or "reference", reference_text,
            )
            stored, entity_id, duplicate = database.save_document_comparison(
                candidate.filename or "candidate", candidate_hash,
                reference.filename or "reference", reference_hash, comparison,
            )
        return DocumentComparisonResult(
            comparison_id=stored["id"], candidate_filename=stored["candidate_filename"],
            reference_filename=stored["reference_filename"], comparison=comparison,
            entity_id=entity_id, duplicate=duplicate,
        )
    except Exception as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.get("/documents/comparisons")
def list_document_comparisons():
    return {"comparisons": database.list_document_comparisons()}


@app.post("/documents/comparisons/{comparison_id}/decision")
def decide_document_comparison(comparison_id: int, request: DocumentReviewDecisionRequest):
    decision, error = database.decide_document_comparison(
        comparison_id, request.decision, request.note
    )
    if error == "not_found":
        raise HTTPException(status_code=404, detail="Document comparison was not found")
    if error == "already_decided":
        raise HTTPException(
            status_code=409,
            detail="This document comparison already has a final human decision",
        )
    return {
        "review": decision,
        "external_action_taken": False,
        "message": "Decision recorded. No document was signed, sent, or modified.",
    }


@app.post(
    "/documents/comparisons/{comparison_id}/revision-draft",
    response_model=RevisionRequestDraftResult,
)
def create_document_revision_draft(comparison_id: int):
    context = database.get_revision_draft_context(comparison_id)
    if context is None:
        raise HTTPException(status_code=404, detail="Document comparison was not found")
    if context["decision"] != "revision_requested":
        raise HTTPException(
            status_code=409,
            detail="A human revision_requested decision is required before drafting follow-up",
        )
    try:
        if context.get("draft_id"):
            existing_draft = RevisionRequestDraft(
                subject=context["draft_subject"], body=context["draft_body"],
                requested_changes=json.loads(context["requested_changes_json"]),
            )
            return RevisionRequestDraftResult(
                draft_id=context["draft_id"], comparison_id=comparison_id,
                draft=existing_draft, duplicate=True,
            )
        comparison = json.loads(context["comparison_json"])
        draft = EmailAnalyzer().create_revision_request_draft(comparison, context["note"])
        stored, duplicate = database.save_revision_draft(comparison_id, draft)
        if duplicate:
            draft = RevisionRequestDraft(
                subject=stored["subject"], body=stored["body"],
                requested_changes=json.loads(stored["requested_changes_json"]),
            )
        return RevisionRequestDraftResult(
            draft_id=stored["id"], comparison_id=comparison_id,
            draft=draft, duplicate=duplicate,
        )
    except Exception as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.get("/documents/revision-drafts")
def list_document_revision_drafts():
    return {"drafts": database.list_revision_drafts()}


@app.post("/documents/revision-drafts/{draft_id}/approve-gmail-draft")
def approve_revision_gmail_draft(draft_id: int, request: RevisionDraftApprovalRequest):
    delivery, error = database.approve_revision_draft_delivery(
        draft_id, request.recipient, request.note
    )
    if error == "not_found":
        raise HTTPException(status_code=404, detail="Revision request draft was not found")
    if error == "already_approved":
        raise HTTPException(status_code=409, detail="Gmail draft creation was already approved")
    return {
        "delivery": delivery,
        "gmail_draft_created": False,
        "message": "Recipient and draft creation approved; execute the delivery separately.",
    }


@app.post("/documents/revision-draft-deliveries/{delivery_id}/execute")
def execute_revision_gmail_draft(delivery_id: int):
    delivery = database.claim_revision_draft_delivery(delivery_id)
    if delivery is None:
        raise HTTPException(status_code=409, detail="Delivery is not approved or already handled")
    try:
        result = GmailOperator(get_gmail_service()).create_standalone_draft(
            delivery["recipient"], delivery["subject"], delivery["body"]
        )
        finished = database.finish_revision_draft_delivery(delivery_id, result["draft_id"])
        return {
            "delivery": finished,
            "gmail_draft_created": True,
            "email_sent": False,
        }
    except Exception as exc:
        database.fail_revision_draft_delivery(delivery_id, str(exc))
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/actions/{action_id}/execute")
def execute_action(action_id: int):
    """Execute one approved draft action. This endpoint never sends email."""
    action = database.claim_approved_action(action_id)
    if action is None:
        raise HTTPException(status_code=409, detail="Action is not approved or already handled")
    try:
        if action["action_type"] == "draft_reply":
            if not action.get("gmail_msg_id"):
                raise ValueError("Action is not linked to a Gmail message")
            result = GmailOperator(get_gmail_service()).create_reply_draft(
                action["gmail_msg_id"], action_reply_text(action), action_reply_subject(action)
            )
        elif action["action_type"] == "calendar_event":
            payload = json.loads(action.get("payload_json") or "{}")
            proposal = CalendarEventProposalUpdateRequest.model_validate(
                payload.get("calendar_event") or {}
            )
            result = CalendarOperator(get_calendar_service()).create_event(proposal.model_dump())
        elif action["action_type"] == "candidate_interview_package":
            payload = json.loads(action.get("payload_json") or "{}")
            proposal = CalendarEventProposalUpdateRequest.model_validate(
                payload.get("calendar_event") or {}
            )
            gmail = GmailOperator(get_gmail_service())
            draft_result = gmail.create_reply_draft(
                action["gmail_msg_id"], payload.get("suggested_reply") or "",
                payload.get("draft_subject"),
            )
            try:
                calendar_result = CalendarOperator(get_calendar_service()).create_event(
                    proposal.model_dump()
                )
            except Exception:
                if draft_result.get("draft_id"):
                    gmail.delete_draft(draft_result["draft_id"])
                raise
            result = {"gmail_draft": draft_result, "calendar_event": calendar_result,
                      "email_sent": False}
        elif action["action_type"] == "create_onboarding_package":
            payload = json.loads(action.get("payload_json") or "{}")
            proposal = CandidateOnboardingPackageUpdateRequest.model_validate(
                payload.get("onboarding") or {}
            )
            package = database.create_onboarding_package(
                action, proposal.model_dump(), build_contract_draft(proposal)
            )
            result = {
                "onboarding_package_id": package["id"],
                "employee_record_created": True,
                "contract_draft_created": True,
                "contract_sent": False,
            }
        elif action["action_type"] == "record_decision":
            if not action.get("entity_id"):
                raise ValueError("Decision is not linked to a company or project")
            payload = json.loads(action.get("payload_json") or "{}")
            proposal = DecisionProposalUpdateRequest.model_validate(
                payload.get("decision_record") or {}
            )
            recorded = database.add_decision(action["entity_id"], RecordDecisionRequest(
                **proposal.model_dump(), status="final", source_email_id=action["email_id"]
            ))
            result = {"decision_id": recorded["id"], "recorded": True}
        elif action["action_type"] == "schedule_follow_up":
            payload = json.loads(action.get("payload_json") or "{}")
            proposal = FollowUpProposalUpdateRequest.model_validate(payload.get("follow_up") or {})
            normalized = proposal.model_dump()
            normalized["follow_up_at"] = normalize_follow_up_time(proposal.follow_up_at)
            scheduled = database.schedule_follow_up(action, normalized)
            result = {"follow_up_id": scheduled["id"], "scheduled": True,
                      "follow_up_at": scheduled["follow_up_at"]}
        elif action["action_type"] == "create_operational_record":
            payload = json.loads(action.get("payload_json") or "{}")
            proposal = OperationalRecordProposal.model_validate(
                payload.get("operational_record") or {}
            )
            record = database.create_operational_record(action, proposal.model_dump())
            result = {"record_id": record["id"], "record_type": record["record_type"],
                      "created": True}
            # Candidate intake has one clear hand-off: after the human accepts the AI
            # finding, place it on the hiring board. Decisions are then made in Trello.
            if record["record_type"] == "candidate_review" and os.getenv("N8N_TRELLO_WEBHOOK_URL"):
                try:
                    trello_result = _dispatch_record_to_trello(record)
                    result["trello"] = trello_result
                except N8nDispatchError as dispatch_error:
                    # The candidate record is still useful and can be retried from Cases.
                    result["trello"] = {"status": "failed", "error": str(dispatch_error)}
        else:
            raise ValueError("This approved action has no external executor")
        finished = database.finish_action(action_id, result)
        payload = json.loads(action.get("payload_json") or "{}")
        candidate_review_id = payload.get("candidate_review_id")
        if candidate_review_id:
            trello = database.get_candidate_trello_dispatch(candidate_review_id)
            webhook_url = os.getenv("N8N_TRELLO_CANDIDATE_RESULT_WEBHOOK_URL")
            if trello and webhook_url:
                sync_payload = {
                    "record_id": candidate_review_id,
                    "card_id": trello["external_id"],
                    "status": (
                        "interview_scheduled" if action["action_type"] == "candidate_interview_package"
                        else "hired" if action["action_type"] == "create_onboarding_package"
                        else "rejection_drafted"
                    ),
                    "message": (
                        "Interview appointment and Gmail draft created."
                        if action["action_type"] == "candidate_interview_package"
                        else "Employee record and draft contract created. Nothing was sent."
                        if action["action_type"] == "create_onboarding_package"
                        else "Rejection Gmail draft created. Nothing was sent."
                    ),
                    "result": result,
                }
                try:
                    sync_result = dispatch_candidate_result(
                        webhook_url, _n8n_shared_secret(), sync_payload
                    )
                    database.record_candidate_trello_sync(
                        candidate_review_id, "trello_result_synced", sync_result
                    )
                except N8nDispatchError as sync_error:
                    database.record_candidate_trello_sync(
                        candidate_review_id, "trello_result_sync_failed",
                        {"error": str(sync_error)},
                    )
        return finished
    except Exception as exc:
        database.fail_action(action_id, str(exc))
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.get("/entities")
def list_entities():
    return {"entities": database.list_entities()}


@app.get("/onboarding-packages/{package_id}/contract", response_class=HTMLResponse)
def view_onboarding_contract(package_id: int):
    package = database.get_onboarding_package(package_id)
    if package is None:
        raise HTTPException(status_code=404, detail="Onboarding package was not found")
    current_draft = build_contract_draft(CandidateOnboardingPackageUpdateRequest(
        employee_name=package["employee_name"], personal_email=package["personal_email"],
        job_title=package["job_title"], start_date=package["start_date"],
        employment_type=package["employment_type"], legal_entity=package["legal_entity"],
        manager=package.get("manager"), work_location=package.get("work_location"),
        hours_per_week=package["hours_per_week"],
    ))
    draft = html.escape(current_draft)
    return HTMLResponse(
        "<!doctype html><html lang='en'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width,initial-scale=1'>"
        "<title>Draft employment agreement</title>"
        "<style>body{font:16px/1.6 system-ui;margin:48px auto;max-width:760px;padding:0 24px;color:#17201d}"
        ".warning{background:#fff4d6;border:1px solid #e0b84c;padding:12px 16px;border-radius:8px}"
        "pre{white-space:pre-wrap;font:inherit}</style></head><body>"
        "<p class='warning'><strong>Draft only.</strong> HR and legal review are required. "
        "Nothing has been sent or signed.</p>"
        f"<pre>{draft}</pre></body></html>"
    )


@app.get("/operational-records")
def list_operational_records(status: str | None = Query(default=None)):
    return {"records": database.list_operational_records(status)}


@app.post("/candidate-reviews/{record_id}/next-action")
def prepare_candidate_review_next_action(record_id: int, request: CandidateReviewDecisionRequest):
    try:
        result = database.prepare_candidate_review_action(
            record_id, request.decision, request.note
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if result is None:
        raise HTTPException(status_code=404, detail="Candidate review was not found")
    return result


@app.post("/integrations/n8n/trello-candidate-status")
def receive_trello_candidate_status(
    request: TrelloCandidateStatusRequest,
    x_ai_operator_secret: str | None = Header(default=None),
):
    _require_n8n_secret(x_ai_operator_secret)
    record = database.get_candidate_review_by_trello_card(request.card_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Candidate review for this Trello card was not found")
    normalized = " ".join(request.list_name.casefold().replace("_", " ").split())
    decision = {
        "interview": "interview", "interview requested": "interview",
        "schedule interview": "interview",
        "rejected": "reject", "reject": "reject",
        "on hold": "hold", "hold": "hold",
        "hired": "hire", "hire": "hire",
    }.get(normalized)
    if decision is None:
        raise HTTPException(status_code=422, detail="Unsupported candidate Trello list")
    try:
        result = database.prepare_candidate_review_action(
            record["id"], decision, f"Selected in Trello list: {request.list_name}"
        )
        duplicate = bool(result.pop("duplicate", False))
    except ValueError as exc:
        if "already waiting" not in str(exc):
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        result = {"record_id": record["id"], "status": record["status"], "action_id": None}
        duplicate = True
    response = {**result, "card_id": request.card_id, "duplicate": duplicate, "decision": decision,
                "requires_human_review": decision != "hold"}
    database.record_candidate_trello_transition(
        record["id"], request.card_id, request.list_name, request.event_id, response
    )
    return response


def _n8n_trello_config():
    webhook_url = os.getenv(
        "N8N_TRELLO_WEBHOOK_URL", "http://127.0.0.1:5678/webhook/ai-operator-trello"
    )
    return webhook_url, _n8n_shared_secret()


def _dispatch_record_to_trello(record: dict):
    """Idempotently dispatch an existing record and return its dispatch state."""
    dispatch, claimed = database.claim_integration_dispatch(record["id"], "trello")
    if not claimed:
        if dispatch["status"] == "completed":
            return {"dispatch": dispatch, "duplicate": True}
        raise N8nDispatchError("This Trello dispatch is already in progress")
    try:
        webhook_url, webhook_secret = _n8n_trello_config()
        result = dispatch_operational_record(webhook_url, webhook_secret, record)
        completed = database.finish_integration_dispatch(dispatch["id"], result)
        return {"dispatch": completed, "duplicate": False}
    except N8nDispatchError as exc:
        database.fail_integration_dispatch(dispatch["id"], str(exc))
        raise


@app.post("/operational-records/{record_id}/send-to-trello")
def send_operational_record_to_trello(record_id: int):
    """Send one human-approved business record to Trello through n8n."""
    record = database.get_operational_record(record_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Operational record was not found")
    try:
        return _dispatch_record_to_trello(record)
    except N8nDispatchError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


def _entity_or_404(entity_name: str):
    entity = database.get_entity(entity_name)
    if entity is None:
        raise HTTPException(status_code=404, detail=f"Entity '{entity_name}' was not found")
    return entity


@app.get("/entities/{entity_name}/timeline")
def get_entity_timeline(entity_name: str):
    entity = _entity_or_404(entity_name)
    return database.entity_timeline(entity["id"])


@app.post("/entities/{entity_name}/aliases")
def add_entity_alias(entity_name: str, request: EntityAliasRequest):
    entity = _entity_or_404(entity_name)
    try:
        return database.add_entity_alias(entity["id"], request.alias)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.post("/entities/{entity_name}/merge")
def merge_entity(entity_name: str, request: EntityMergeRequest):
    """Merge a source entity into the canonical entity named in the URL."""
    target = _entity_or_404(entity_name)
    try:
        return database.merge_entities(target["id"], request.source_entity)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.post("/entities/{entity_name}/decisions")
def record_entity_decision(entity_name: str, decision: RecordDecisionRequest):
    entity = _entity_or_404(entity_name)
    try:
        return database.add_decision(entity["id"], decision)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.get("/entities/{entity_name}/status", response_model=EntityStatusBrief)
def get_entity_status(entity_name: str):
    entity = _entity_or_404(entity_name)
    context = database.entity_context(entity["id"])
    try:
        return EmailAnalyzer().create_status_brief(context)
    except Exception as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/monitor/open-loops")
def monitor_open_loops(request: OpenLoopMonitorRequest):
    return OpenLoopMonitor(database).run(request.due_within_days)


@app.post("/monitor/follow-ups")
def monitor_follow_ups():
    return FollowUpMonitor(database).run()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8000)
