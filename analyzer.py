import json
import os

from openai import OpenAI

from models import DocumentAnalysis, EmailAnalysis, EmailRequest, EntityStatusBrief


SYSTEM_PROMPT = """
You are a cautious AI executive email operator. Identify commitments, decisions,
deadlines and follow-up actions. Never claim an action was executed. External
actions always require human approval. Return JSON with: category (information,
task, meeting, decision, follow_up, other), summary, contact_name,
company_or_project, commitment_title, deadline (ISO-8601 or null), urgency
(low, medium, high), proposed_action, suggested_reply, requires_approval, and
confidence (0 to 1). Use null for unknown or inapplicable fields.
"""


class EmailAnalyzer:
    def __init__(self, client=None, model: str | None = None):
        self.client = client or OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
        self.model = model or os.getenv("OPENAI_MODEL", "gpt-4o-mini")

    def analyze(self, request: EmailRequest) -> EmailAnalysis:
        response = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": f"Sender: {request.sender or 'unknown'}\nSubject: {request.subject}\nBody: {request.body}"},
            ],
            response_format={"type": "json_object"},
            temperature=0,
        )
        content = response.choices[0].message.content
        if not content:
            raise ValueError("The model returned an empty analysis")
        return EmailAnalysis.model_validate(json.loads(content))

    def analyze_document(self, filename: str, text: str) -> DocumentAnalysis:
        response = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a cautious business document review assistant, not a lawyer. "
                        "Use only the supplied document text and do not invent clauses or facts. "
                        "Flag uncertainty and missing information. Return JSON with document_type "
                        "(contract, proposal, report, invoice, or other), summary, "
                        "company_or_project, parties, obligations, deadlines, financial_terms, "
                        "risk_indicators, missing_information, recommendation (review, revise, "
                        "approve, or reject), recommendation_reason, and confidence (0 to 1). "
                        "All collection fields must be arrays of short strings."
                    ),
                },
                {"role": "user", "content": f"Filename: {filename}\n\nDocument text:\n{text}"},
            ],
            response_format={"type": "json_object"},
            temperature=0,
        )
        content = response.choices[0].message.content
        if not content:
            raise ValueError("The model returned an empty document analysis")
        return DocumentAnalysis.model_validate(json.loads(content))

    def create_status_brief(self, context: dict) -> EntityStatusBrief:
        response = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a cautious executive operator. Produce a factual status brief "
                        "using only the supplied structured records. Do not invent events, dates, "
                        "decisions, blockers, or actions. Clearly list missing information. Return "
                        "JSON with entity, current_status, recent_activity, open_commitments, "
                        "upcoming_meetings, pending_actions, decisions, blockers, recommended_next_action, and "
                        "missing_information. Every list contains short strings."
                    ),
                },
                {"role": "user", "content": json.dumps(context, default=str)},
            ],
            response_format={"type": "json_object"},
            temperature=0,
        )
        content = response.choices[0].message.content
        if not content:
            raise ValueError("The model returned an empty status brief")
        data = json.loads(content)
        source_entity = context.get("entity")
        canonical_name = (
            source_entity.get("name") if isinstance(source_entity, dict) else source_entity
        )
        if not canonical_name:
            raise ValueError("Status context has no canonical entity name")
        data["entity"] = canonical_name
        return EntityStatusBrief.model_validate(data)
