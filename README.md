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
- Turns AI-detected decision requests into editable, approval-gated business records.
- Records decisions in entity context and the audit log.
- Schedules AI-detected follow-ups and creates an approval-gated draft when due.
- Converts operational findings into editable tasks, CRM leads, finance reviews,
  support cases, document-review tasks, and escalation records.
- Prevents duplicate storage when a Gmail message ID is provided.
- Manually imports only emails carrying a selected Gmail label.
- Creates a Gmail draft in the original thread after explicit approval.
- Groups related emails, commitments, actions, and decisions by company or project.
- Produces a grounded status brief with a recommended next action.
- Reviews uploaded PDF, DOCX, and TXT business documents and links them to context.

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

### Import labeled document attachments

Apply the `AI-Operator` label to a test email containing a PDF, DOCX, or TXT
attachment, then call `POST /gmail/import-attachments`:

```json
{
  "label": "AI-Operator",
  "max_messages": 10
}
```

The operator downloads supported attachments, extracts their text, analyzes new
files, stores their Gmail source, and links the identified company or project to
its context. Previously imported attachments are skipped. If the same file was
already uploaded through another route, the existing document is reused without
another AI call. Errors are reported per file and do not stop the batch.

The importer does not alter labels, mark messages as read, delete attachments,
or send replies. Automatic comparison waits for a trusted reference library that
can select an appropriate baseline.

### Contract intake automation

`POST /automation/contract-intake` orchestrates the full safe intake path for
labeled Gmail attachments in one run:

```text
discover attachment -> deduplicate -> extract -> AI analyze
-> select human-trusted reference -> AI compare -> queue human review
```

Each run is persisted and visible through `GET /automation/runs`. Documents
without a safe reference stop at `analyzed_only` with an explicit next step.
Documents with a match appear in `review_ready`. The automation never makes the
human approve/revise/reject decision and never creates or sends an email.

Recurring intake is opt-in through `PUT /automation/contract-intake/schedule`.
It is disabled by default and stores its interval, Gmail label, last run status,
result, and error. The local scheduler atomically claims due work so overlapping
runs cannot start. It performs only the safe intake-to-review workflow; human
decisions and Gmail draft creation remain separate approval-gated actions.

`GET /automation/review-queue` turns pending comparisons into a transparent
priority queue. Its deterministic score weighs high- and medium-significance
differences, missing information, the AI recommendation, and waiting time. The
dashboard explains every priority reason; the score orders human work but never
makes the final decision.

`POST /automation/executive-briefing` creates a grounded cross-system briefing
from open commitments, prioritized document reviews, upcoming meetings, recent
decisions, and automation-run health. It returns priorities, urgent risks,
recommended next actions, and missing information, then stores the briefing for
audit/history. It summarizes records only and performs no action.

`POST /operator/ask` is the central natural-language entry point. Entity names
and aliases in the question are matched deterministically before retrieval; a
question without an entity uses bounded global operator context. The model can
cite only evidence keys supplied by retrieval, and unsupported keys are removed
before returning the answer. Recommended actions remain suggestions only.

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

The default dashboard follows one email-first workflow:

1. Add the Gmail label `AI-Operator` to relevant messages.
2. Click **Scan Gmail**. One audited automation run extracts tasks, deadlines,
   and proposed actions, then checks existing open loops for follow-up.
3. Review the findings and approve or reject each proposed action.
4. Execute an approved action: create a Gmail draft, create a Calendar event, or
   record an internal business decision. Nothing is sent automatically.

Business context, document comparison, scheduling, and audit history remain
available as secondary tools without interrupting this main flow.

An optional **Automatic scan** control runs the same bounded, audited inbox
workflow on a local interval. It is disabled by default and never sends mail.

AI triage recognizes multiple work scenarios: sales, customer service, finance,
contracts, meetings, approvals, operations, and escalations. A single email may
produce multiple separate work items, each with its own deadline, urgency,
recommended action, and approval gate.

The dashboard groups these items by source email in one **AI work queue**. Each
finding is shown together with its proposed action and available approval or
draft controls. Deadline monitoring does not create a second reminder when a
primary action for the same work item is already pending.

The same inbox run also imports supported Gmail attachments. Documents are
analyzed automatically and, when a trusted reference exists, compared and placed
in the human document review queue.

The dashboard shows the latest inbox run below **Scan Gmail**, including new and
skipped messages, routed documents, errors, and completion time.

Reply actions include an editable subject/body preview. Saving changes only
updates the local proposal; the approved **Create Gmail draft** action creates a
draft in Gmail and never sends it.

Meeting actions include an editable Calendar proposal. After approval, **Create
Calendar event** writes the event with `sendUpdates=none`, so attendee invitation
emails are not sent automatically.

Decision findings include an editable title, final outcome, and rationale. Saving
only updates the proposal. After explicit approval, **Record decision** stores it
under the company or project linked to the source email, making it available to
future status answers and executive briefings. If a reply is also required, AI
creates that as a separate follow-up item with its own approval gate.

Follow-up findings include an editable due time, subject, and draft body. After
approval, **Activate follow-up** stores the schedule internally. Each manual or
scheduled inbox scan checks due follow-ups and places a new Gmail draft proposal
in the work queue. The draft still requires separate approval and is never sent
automatically. Completing the underlying work item cancels its pending follow-up.

Other AI findings use the same compact approval flow. The operator maps tasks,
sales leads, payments, customer issues, contract reviews, and risks to structured
internal business records. Title, owner, due date, priority, next action, notes,
and optional amount/currency remain editable before approval. These local records
are deliberately connector-neutral: a later adapter can synchronize them with
Trello, Asana, a CRM, support desk, or finance system without changing AI triage.

Ready-to-send fictional examples are available in
[`docs/test-emails.md`](docs/test-emails.md).

The dashboard calls the same audited API endpoints documented above. It does not
introduce automatic email sending or bypass approval checks.

## Google Calendar context and approved event creation

The operator can import a bounded window of Calendar events as a second context
source. Meeting emails can also produce an editable Calendar proposal. The event
is created only after explicit action approval and a separate **Create Calendar
event** click. Attendee update emails are disabled.

Before the first import:

1. Enable the **Google Calendar API** in the same Google Cloud project.
2. Stop the API if it is running.
3. Run `python calendar_auth.py` and approve the `calendar.events` permission.
4. Restart the API.

The shared token covers both Gmail and Calendar. Adding the Calendar scope requires
one new authorization even when Gmail was already connected.

If an older token only has `calendar.readonly`, delete `token.pickle`, run
`python calendar_auth.py`, and complete Google authorization again.

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

## Document and contract review

Use `POST /documents/analyze` in the interactive API documentation and select one
PDF, DOCX, or TXT file. The operator extracts its text locally, asks AI for a
structured review, stores the result, and links the identified company or project
to its timeline and status context. `GET /documents` lists prior reviews.

The review includes document type, summary, parties, obligations, deadlines,
financial terms, risk indicators, missing information, and a cautious
review/revise/approve/reject recommendation. It is an AI review aid, not legal
advice, and always requires human review. The application does not edit, sign,
send, or otherwise act on a document.

Uploads are limited to 10 MB and 100,000 extracted characters are sent for
analysis. Password-protected files are unsupported. Image-only/scanned PDFs need
OCR, which is intentionally left for a later iteration.

### Trusted reference library

Trust is assigned only by a human. After reviewing an existing document, mark it
as an approved baseline with `POST /documents/{document_id}/trusted-reference`:

```json
{
  "label": "Approved Carrefour services template",
  "note": "Approved by legal operations on 2026-09-02."
}
```

List human-designated references with `GET /documents/trusted-references`. To
compare an imported or uploaded document automatically, call
`POST /documents/{document_id}/compare-with-trusted-reference`.

Selection is deterministic: the reference must be active and have the same
document type; a reference for the same entity is preferred over a global
document-type reference. The response always exposes the selected reference ID,
label, and selection reason. When no safe match exists, the API returns HTTP 409
instead of guessing.

### Compare with a trusted reference

Use `POST /documents/compare` and upload two files:

- `candidate`: the new agreement being reviewed.
- `reference`: a previously approved agreement or trusted template.

The AI identifies added, removed, and materially changed terms, assigns low,
medium, or high significance, explains the likely business impact, and proposes
a resolution. The grounded comparison is stored and added to the identified
entity's context. Re-uploading the same candidate/reference pair returns the
existing comparison. Inspect saved results with `GET /documents/comparisons`.

The quality of the result depends on the reference document being genuinely
trusted and relevant. The comparison remains a review aid and never signs,
accepts, rejects, or transmits a contract.

Every new material difference can include candidate and reference evidence. PDF
locations use page markers, DOCX locations use paragraph/table markers, and TXT
locations use line ranges. Excerpts must be copied verbatim by the model and are
then checked deterministically against the extracted source. The dashboard marks
each excerpt as verified or warns the reviewer to inspect the original. Missing
evidence remains explicit instead of being invented.

### Human review decision

Every new comparison starts with `review_status: pending_review`. A human can
record exactly one final decision with:

`POST /documents/comparisons/{comparison_id}/decision`

```json
{
  "decision": "revision_requested",
  "note": "Restore the approved 30-day termination period."
}
```

Allowed decisions are `approved`, `revision_requested`, and `rejected`. The note
is mandatory so the business reasoning remains auditable. Repeating or changing
a final decision returns HTTP 409. This endpoint records the decision only; it
does not sign, modify, or send the document.

### Prepare a revision-request draft

After a human records `revision_requested`, call:

`POST /documents/comparisons/{comparison_id}/revision-draft`

The AI uses only the stored material differences and the human review note to
prepare a subject, email body, and explicit list of requested changes. The draft
is stored idempotently: repeated calls return the same draft and do not call the
model again. Inspect all prepared drafts with `GET /documents/revision-drafts`.

This is an internal draft only. No recipient is selected, no Gmail draft is
created, and no message is sent. Connecting the approved text to Gmail remains a
separate, explicitly controlled step.

### Create an approved Gmail draft

Approve the exact recipient for a prepared revision draft:

`POST /documents/revision-drafts/{draft_id}/approve-gmail-draft`

```json
{
  "recipient": "contracts@example.com",
  "note": "Recipient and revision wording manually verified."
}
```

This records approval but does not yet call Gmail. Use the returned delivery ID
with `POST /documents/revision-draft-deliveries/{delivery_id}/execute` to create
the Gmail draft. Atomic state transitions prevent duplicate execution. The
operator uses Gmail's draft endpoint only; there is still no email-send endpoint.

## Tests

```powershell
python -m unittest discover -s tests -v
```

## Security

Git ignores `.env`, `credentials.json`, `token.pickle`, and local databases.
Never share these files. Revoke and replace any credential that has appeared in
a public repository or log.

## Next steps

1. Mark one reviewed contract as a trusted reference.
2. Import a labeled Gmail contract and compare it with that reference.
3. Show page and clause citations for every material difference.
