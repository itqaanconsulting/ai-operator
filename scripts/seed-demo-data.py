"""Create a disposable, fictional database for screenshots and demos."""

import argparse
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from database import Database
from models import ActionStatus, EmailAnalysis, EmailRequest, EmailWorkItem


def candidate_analysis(name: str, role: str, skills: str) -> EmailAnalysis:
    return EmailAnalysis(
        category="task",
        scenario="hr",
        summary=f"{name} applied for the {role} position.",
        contact_name=name,
        work_items=[EmailWorkItem(
            kind="job_application",
            title=f"Review {name} for {role}",
            proposed_action="Add candidate to the hiring board.",
            owner="Recruiting",
            urgency="medium",
            notes=f"Relevant experience: {skills}.",
        )],
    )


def create_candidate_record(
    db: Database, *, name: str, role: str, email: str, message_id: str, skills: str
) -> dict:
    _, _, action_id = db.save_analysis(
        EmailRequest(
            sender=f"{name} <{email}>",
            subject=f"Application for {role} - {name}",
            body=f"I would like to apply for {role}. My experience includes {skills}.",
            gmail_msg_id=message_id,
        ),
        candidate_analysis(name, role, skills),
    )
    db.decide_action(action_id, ActionStatus.APPROVED, "Confirmed in fictional demo")
    action = db.claim_approved_action(action_id)
    proposal = json.loads(action["payload_json"])["operational_record"]
    record = db.create_operational_record(action, proposal)
    db.finish_action(action_id, {"record_id": record["id"], "created": True})
    dispatch, _ = db.claim_integration_dispatch(record["id"], "trello")
    db.finish_integration_dispatch(dispatch["id"], {
        "id": f"demo-card-{record['id']}",
        "url": f"https://trello.com/c/fictional-demo-{record['id']}",
        "name": record["title"],
    })
    return record


def build_demo_database(path: Path) -> None:
    if path.exists():
        path.unlink()
    db = Database(str(path))
    db.init()

    miguel = create_candidate_record(
        db, name="Miguel Santos", role="Backend Developer",
        email="miguel.santos@example.com", message_id="demo-gmail-miguel",
        skills="Python, FastAPI, PostgreSQL, and Docker",
    )
    interview = db.prepare_candidate_review_action(
        miguel["id"], "interview", "Selected in fictional Trello demo"
    )
    start = (datetime.now().astimezone() + timedelta(days=1)).replace(
        hour=10, minute=0, second=0, microsecond=0
    )
    db.update_action_payload(
        interview["action_id"],
        {"calendar_event": {
            "title": "Interview - Miguel Santos",
            "start_at": start.isoformat(),
            "end_at": (start + timedelta(minutes=30)).isoformat(),
            "location": "Microsoft Teams",
            "attendees": ["miguel.santos@example.com"],
        }},
        {"candidate_interview_package"},
    )

    amina = create_candidate_record(
        db, name="Amina Yusuf", role="Automation Engineer",
        email="amina.yusuf@example.com", message_id="demo-gmail-amina",
        skills="n8n, Python, APIs, and process automation",
    )
    db.prepare_candidate_review_action(
        amina["id"], "hold", "Selected in fictional Trello demo"
    )

    _, _, sarah_action_id = db.save_analysis(
        EmailRequest(
            sender="Sarah Chen <sarah.chen@example.com>",
            subject="Application for Frontend Developer - Sarah Chen",
            body="I have six years of experience with TypeScript, Angular, and accessibility.",
            gmail_msg_id="demo-gmail-sarah",
        ),
        candidate_analysis(
            "Sarah Chen", "Frontend Developer", "TypeScript, Angular, and accessibility"
        ),
    )

    run_id = db.start_automation_run("inbox_automation")
    db.finish_automation_run(run_id, {
        "found": 3,
        "processed": [{
            "gmail_msg_id": "demo-gmail-sarah",
            "action_id": sarah_action_id,
        }],
        "skipped": ["demo-gmail-miguel", "demo-gmail-amina"],
        "errors": [],
        "follow_up_monitor": {"created": []},
        "open_loop_monitor": {"created": []},
        "document_automation": {"review_ready": []},
        "trigger": "demo",
    })


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", default="demo.db")
    args = parser.parse_args()
    path = Path(args.database).resolve()
    build_demo_database(path)
    print(f"Created fictional demo database: {path}")


if __name__ == "__main__":
    main()
