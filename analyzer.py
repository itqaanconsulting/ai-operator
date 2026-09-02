import json
import os

from openai import OpenAI

from models import (
    DocumentAnalysis, DocumentComparison, EmailAnalysis, EmailRequest,
    EntityStatusBrief, RevisionRequestDraft,
    ExecutiveBriefing,
    OperatorAnswer,
)


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

    def compare_documents(self, candidate_filename: str, candidate_text: str,
                          reference_filename: str, reference_text: str) -> DocumentComparison:
        response = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a cautious business contract comparison assistant, not a lawyer. "
                        "Compare the candidate only against the supplied reference. Do not invent "
                        "clauses. Distinguish absent text from ambiguous text and flag uncertainty. "
                        "Return JSON with company_or_project, executive_summary, material_differences, "
                        "added_terms, removed_terms, unchanged_key_terms, missing_information, "
                        "recommendation (review, revise, approve, or reject), recommendation_reason, "
                        "and confidence. Each material difference has topic, reference_position, "
                        "candidate_position, significance (low, medium, or high), impact, and "
                        "suggested_resolution, candidate_evidence, and reference_evidence. Each evidence "
                        "object has location copied from the nearest [SOURCE ...] marker and excerpt copied "
                        "verbatim from that source. Never invent an excerpt; use null when unsupported. "
                        "All other collection fields are arrays of short strings."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"REFERENCE: {reference_filename}\n{reference_text[:50_000]}\n\n"
                        f"CANDIDATE: {candidate_filename}\n{candidate_text[:50_000]}"
                    ),
                },
            ],
            response_format={"type": "json_object"},
            temperature=0,
        )
        content = response.choices[0].message.content
        if not content:
            raise ValueError("The model returned an empty document comparison")
        comparison = DocumentComparison.model_validate(json.loads(content))
        for difference in comparison.material_differences:
            self._verify_evidence(difference.candidate_evidence, candidate_text)
            self._verify_evidence(difference.reference_evidence, reference_text)
        return comparison

    @staticmethod
    def _verify_evidence(evidence, source_text: str):
        if evidence is None:
            return
        normalized_excerpt = " ".join(evidence.excerpt.split()).casefold()
        normalized_source = " ".join(source_text.split()).casefold()
        evidence.verified = bool(normalized_excerpt and normalized_excerpt in normalized_source)

    def create_revision_request_draft(self, comparison: dict, human_note: str) -> RevisionRequestDraft:
        response = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Write a concise, professional revision-request email draft using only the "
                        "supplied document comparison and human review note. Do not add legal claims, "
                        "deadlines, recipients, or changes that are not in the supplied records. "
                        "Return JSON with subject, body, and requested_changes (an array of short strings). "
                        "Make clear that the attached/new agreement should be revised; do not claim it "
                        "has been rejected, sent, signed, or legally reviewed."
                    ),
                },
                {
                    "role": "user",
                    "content": json.dumps({"comparison": comparison, "human_note": human_note}),
                },
            ],
            response_format={"type": "json_object"},
            temperature=0,
        )
        content = response.choices[0].message.content
        if not content:
            raise ValueError("The model returned an empty revision request draft")
        return RevisionRequestDraft.model_validate(json.loads(content))

    def create_executive_briefing(self, context: dict) -> ExecutiveBriefing:
        response = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a cautious AI executive operator. Create a concise briefing using "
                        "only the supplied structured records. Prioritize overdue commitments and "
                        "high-risk document reviews. Distinguish business risks from automation health. "
                        "Do not invent events, decisions, deadlines, or completed actions. Return JSON "
                        "with headline, executive_summary, top_priorities, urgent_risks, upcoming_meetings, "
                        "automation_health, recommended_next_actions, and missing_information. All fields "
                        "except headline and executive_summary are arrays of short strings."
                    ),
                },
                {"role": "user", "content": json.dumps(context, default=str)},
            ],
            response_format={"type": "json_object"},
            temperature=0,
        )
        content = response.choices[0].message.content
        if not content:
            raise ValueError("The model returned an empty executive briefing")
        return ExecutiveBriefing.model_validate(json.loads(content))

    def answer_operator_question(self, question: str, context: dict) -> OperatorAnswer:
        response = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a cautious AI executive operator. Answer the question using only "
                        "the supplied records. If the records do not support an answer, say so and "
                        "list the missing information. Evidence keys must be copied exactly from the "
                        "available_evidence_keys list; never invent a key. Return JSON with answer, "
                        "matched_entities, evidence_keys, recommended_next_actions, missing_information, "
                        "and confidence from 0 to 1. Do not claim any recommended action was executed."
                    ),
                },
                {"role": "user", "content": json.dumps({"question": question, **context}, default=str)},
            ],
            response_format={"type": "json_object"},
            temperature=0,
        )
        content = response.choices[0].message.content
        if not content:
            raise ValueError("The model returned an empty operator answer")
        answer = OperatorAnswer.model_validate(json.loads(content))
        allowed = set(context.get("available_evidence_keys", []))
        answer.evidence_keys = [key for key in answer.evidence_keys if key in allowed]
        answer.matched_entities = context.get("matched_entity_names", [])
        return answer

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
