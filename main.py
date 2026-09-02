import os

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query

from analyzer import EmailAnalyzer
from database import Database
from gmail_auth import get_gmail_service
from gmail_operator import GmailOperator, action_reply_text
from models import (
    ActionStatus,
    AnalysisResult,
    DecisionRequest,
    EmailRequest,
    GmailImportRequest,
)

load_dotenv()

database = Database(os.getenv("DATABASE_PATH", "operator.db"))
app = FastAPI(title="AI Commitment Operator", version="0.2.0")


@app.on_event("startup")
def startup_event():
    database.init()


@app.get("/health")
def health():
    return {
        "status": "ok",
        "gmail_polling_enabled": False,
        "gmail_manual_import_enabled": True,
        "automatic_sending_enabled": False,
    }


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


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8000)
