# AI Commitment Operator

A safe first step toward an AI executive operator. The application analyzes
emails, identifies commitments and deadlines, proposes next actions, and places
those actions in an approval queue. It never performs external actions
automatically.

## Current pilot

- Analyzes manually submitted emails with OpenAI.
- Recognizes information, tasks, meetings, decisions, and follow-ups.
- Stores emails, commitments, and proposed actions in SQLite.
- Supports human approval and rejection.
- Records decisions in an audit log.
- Prevents duplicate storage when a Gmail message ID is provided.
- Manually imports only emails carrying a selected Gmail label.
- Creates a Gmail draft in the original thread after explicit approval.
- Groups related emails, commitments, actions, and decisions by company or project.
- Produces a grounded status brief with a recommended next action.

The Gmail poller does not start automatically. Importing does not change labels
or mark messages as read. The operator can only create drafts; it has no endpoint
that sends email.

## Installation

```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

Create a local `.env` file containing at least:

```dotenv
OPENAI_API_KEY=your-key
OPENAI_MODEL=gpt-4o-mini
DATABASE_PATH=operator.db
```

Start the API:

```powershell
uvicorn main:app --reload
```

Open `http://127.0.0.1:8000/docs` to use the interactive API documentation.

For the operator dashboard, open `http://127.0.0.1:8000/dashboard`.

## Analyze an email

Call `POST /analyze-email`:

```json
{
  "sender": "jane@example.com",
  "subject": "Decision required for Project X",
  "body": "Can you confirm by Friday whether we approve the proposal?",
  "gmail_msg_id": "optional-unique-id"
}
```

Inspect the queues with:

- `GET /commitments?status=open`
- `GET /actions?status=pending_approval`

Approve an action without executing it:

`POST /actions/{id}/approve`

```json
{
  "note": "Proposal reviewed; the draft may be prepared."
}
```

A second decision for the same action returns HTTP 409, preventing accidental
duplicate handling.

## Safe Gmail workflow

Create a Gmail label named `AI-Operator` and apply it only to a test message.
Then import up to ten labeled messages with `POST /gmail/import`:

```json
{
  "label": "AI-Operator",
  "max_results": 10
}
```

Review `GET /actions?status=pending_approval` and approve the intended action.
Approval still performs no external operation. Only then create the draft with:

`POST /actions/{id}/execute`

Only an approved `draft_reply` action linked to a Gmail message can be executed.
The result is a Gmail draft, not a sent message. An atomic status transition
prevents duplicate execution.

## Company and project context

Every analyzed `company_or_project` value is linked to a persistent entity.
Matching is case-insensitive, so `Carrefour`, `carrefour`, and `CARREFOUR` resolve
to the same record.

List known entities:

`GET /entities`

Inspect the chronological history for an entity:

`GET /entities/Carrefour/timeline`

Record an explicit business decision:

`POST /entities/Carrefour/decisions`

```json
{
  "title": "Campaign direction",
  "decision": "Proceed with the campaign.",
  "rationale": "The forecast meets the target.",
  "status": "final",
  "source_email_id": null
}
```

Ask for a current status brief:

`GET /entities/Carrefour/status`

The application first retrieves only records linked to the requested entity.
AI then turns that structured context into a concise status, open commitments,
pending actions, decisions, blockers, missing information, and one recommended
next action. The model is explicitly instructed not to invent facts outside the
retrieved records.

### Entity aliases and merging

Add an alternate name to an existing canonical entity:

`POST /entities/Carrefour/aliases`

```json
{
  "alias": "Carrefour NL"
}
```

The alias resolves to the same timeline and status brief. It is rejected when it
already belongs to another entity.

When two existing entities represent the same company or project, merge the
duplicate into the canonical entity:

`POST /entities/Carrefour/merge`

```json
{
  "source_entity": "Carrefour campaign"
}
```

The merge moves linked emails and decisions to `Carrefour`, preserves
`Carrefour campaign` and its aliases as alternate names, removes the duplicate
entity record, and writes an audit event. Review both timelines before merging;
the API does not currently provide an automatic undo operation.

## Proactive open-loop monitoring

Run the monitor manually with:

`POST /monitor/open-loops`

```json
{
  "due_within_days": 3
}
```

The monitor checks every open commitment and classifies valid ISO-8601 deadlines
as `overdue`, `due_soon`, or not yet due. It creates a pending
`open_loop_review` action for overdue and approaching work. Running the monitor
again does not create duplicate reminders for the same commitment, deadline, and
alert type. Missing and invalid deadlines are reported explicitly rather than
guessed.

Close a resolved loop with:

`POST /commitments/{commitment_id}/complete`

```json
{
  "note": "Confirmed during the client call."
}
```

Completing a commitment records an audit event and automatically rejects any
still-pending monitor reminder for that commitment. The monitor is currently
triggered through the API; a scheduler can invoke the same operation later.

## Operator dashboard

The dashboard provides a client-friendly interface for the existing controlled
workflows:

- View entity, commitment, approval, and overdue counts.
- Select a company or project and generate its grounded AI status brief.
- Review open commitments and mark completed work.
- Approve or reject proposed actions.
- Create a Gmail draft from an approved `draft_reply` action.
- Run the open-loop monitor and inspect its generated reminders.

The dashboard calls the same audited API endpoints documented above. It does not
introduce automatic email sending or bypass approval checks.

## Read-only Google Calendar context

The operator can import a bounded window of Calendar events as a second context
source. It requests `calendar.readonly`; no code path creates, edits, or deletes
Google Calendar events.

Before the first import:

1. Enable the **Google Calendar API** in the same Google Cloud project.
2. Stop the API if it is running.
3. Run `python calendar_auth.py` and approve the additional read-only permission.
4. Restart the API.

The shared token covers both Gmail and Calendar. Adding the Calendar scope requires
one new authorization even when Gmail was already connected.

Import a bounded event window:

`POST /calendar/import`

```json
{
  "calendar_id": "primary",
  "days_before": 30,
  "days_after": 90
}
```

Events are stored idempotently by Google event ID and calendar ID. Titles,
descriptions, and locations are matched deterministically against canonical entity
names and aliases. Unmatched events remain stored and are reported; the system does
not invent a company or project association.

Inspect imported events with `GET /calendar/events`. Matched meetings appear in the
entity timeline, grounded status brief, and operator dashboard.

## Tests

```powershell
python -m unittest discover -s tests -v
```

## Security

Git ignores `.env`, `credentials.json`, `token.pickle`, and local databases.
Never share these files. Revoke and replace any credential that has appeared in
a public repository or log.

## Next steps

1. Authorize Calendar and import one Carrefour test meeting.
2. Verify that the meeting appears in the entity status brief and dashboard.
3. Schedule the open-loop monitor to run periodically.
