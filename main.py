import json
import os
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from analyzer import EmailAnalyzer
from automation_scheduler import AutomationScheduler
from calendar_auth import get_calendar_service
from calendar_operator import CalendarOperator
from contract_automation import ContractIntakeAutomation
from database import Database
from document_processor import extract_document
from gmail_auth import get_gmail_service
from gmail_operator import GmailOperator, action_reply_text
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
)
from open_loops import OpenLoopMonitor

load_dotenv()

database = Database(os.getenv("DATABASE_PATH", "operator.db"))
app = FastAPI(title="AI Commitment Operator", version="0.19.0")
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


scheduler = AutomationScheduler(database, _execute_contract_intake)


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
        "gmail_attachment_import_enabled": True,
        "trusted_reference_library_enabled": True,
        "contract_intake_automation_enabled": True,
        "contract_intake_scheduler_configured": bool(database.get_contract_schedule()["enabled"]),
        "automatic_sending_enabled": False,
        "calendar_manual_import_enabled": True,
        "calendar_writes_enabled": False,
        "document_analysis_enabled": True,
        "document_signing_enabled": False,
        "document_comparison_enabled": True,
        "document_evidence_verification_enabled": True,
        "prioritized_human_review_queue_enabled": True,
        "grounded_executive_briefing_enabled": True,
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
        if action["action_type"] != "draft_reply":
            raise ValueError("Only draft_reply actions can currently be executed")
        if not action.get("gmail_msg_id"):
            raise ValueError("Action is not linked to a Gmail message")
        result = GmailOperator(get_gmail_service()).create_reply_draft(
            action["gmail_msg_id"], action_reply_text(action)
        )
        return database.finish_action(action_id, result)
    except Exception as exc:
        database.fail_action(action_id, str(exc))
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.get("/entities")
def list_entities():
    return {"entities": database.list_entities()}


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


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8000)
