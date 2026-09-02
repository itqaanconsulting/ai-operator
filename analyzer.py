import json
import os

from openai import OpenAI

from models import (
    DocumentAnalysis, DocumentComparison, EmailAnalysis, EmailRequest,
    EntityStatusBrief, RevisionRequestDraft,
    ExecutiveBriefing,
    OperatorAnswer,
    OperatorPlan,
)


SYSTEM_PROMPT = """
You are a cautious AI executive email operator. Identify every distinct task,
decision, meeting, follow-up, payment, contract review, sales lead, customer
issue, or risk in the email. Never claim an action was executed. External actions
always require human approval. Classify the overall scenario as general, sales,
customer_service, finance, contract, meeting, approval, operations, or escalation.
Return JSON with category (information, task, meeting, decision, follow_up, other),
scenario, summary, contact_name, company_or_project, confidence (0 to 1), and
work_items. Each work item has kind, title, deadline (ISO-8601 or null), urgency,
proposed_action, suggested_reply, and requires_approval. Return an empty work_items
array when the email is informational. Meeting items also include start_at and
end_at as ISO-8601 values, location, and attendees. Use null or an empty array
when meeting details are unknown. Do not combine unrelated work into one item.
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
        return EmailAnalysis.model_validate(self._normalize_email_analysis(json.loads(content)))

    @staticmethod
    def _normalize_email_analysis(data: dict) -> dict:
        category = str(data.get("category") or "other").strip().casefold()
        category_aliases = {
            "approval": "decision", "contract": "task", "finance": "task",
            "payment": "task", "sales": "task", "customer_service": "task",
            "customer service": "task", "operations": "task", "escalation": "task",
        }
        allowed_categories = {"information", "task", "meeting", "decision", "follow_up", "other"}
        data["category"] = category if category in allowed_categories else category_aliases.get(category, "other")

        scenario_text = str(data.get("scenario") or "").strip().casefold()
        scenario_keywords = (
            ("escalation", ("escalat", "urgent", "failure", "failing", "outage")),
            ("finance", ("financ", "payment", "invoice", "billing")),
            ("contract", ("contract", "agreement", "legal")),
            ("sales", ("sales", "lead", "proposal", "commercial")),
            ("customer_service", ("customer", "support", "complaint", "order")),
            ("meeting", ("meeting", "call", "appointment", "review meeting")),
            ("approval", ("approval", "approve", "decision")),
            ("operations", ("operation", "delivery", "workflow", "launch")),
        )
        allowed_scenarios = {item[0] for item in scenario_keywords} | {"general"}
        if scenario_text in allowed_scenarios:
            data["scenario"] = scenario_text
        else:
            searchable = " ".join(filter(None, [scenario_text, str(data.get("summary") or ""), category]))
            data["scenario"] = next(
                (scenario for scenario, keywords in scenario_keywords
                 if any(keyword in searchable for keyword in keywords)),
                "general",
            )

        allowed_kinds = {
            "task", "decision", "meeting", "follow_up", "payment", "contract_review",
            "sales_lead", "customer_issue", "risk", "other",
        }
        kind_aliases = {
            "approval": "decision", "contract": "contract_review", "contract review": "contract_review",
            "sales": "sales_lead", "sales lead": "sales_lead", "customer service": "customer_issue",
            "customer_service": "customer_issue", "invoice": "payment", "finance": "payment",
            "follow-up": "follow_up", "follow up": "follow_up", "escalation": "risk",
        }
        for item in data.get("work_items") or []:
            kind = str(item.get("kind") or "other").strip().casefold()
            item["kind"] = kind if kind in allowed_kinds else kind_aliases.get(kind, "other")
        return data

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

    def create_operator_plan(self, goal: str, context: dict) -> OperatorPlan:
        response = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a cautious AI executive action planner. Build a short, executable "
                        "plan using only the supplied records. Never claim an action was performed. "
                        "Every draft, create, update, or follow-up step must require approval. Read "
                        "and analysis steps may omit approval. Evidence keys must be copied exactly "
                        "from available_evidence_keys. Return JSON with goal, summary, steps, risks, "
                        "missing_information, and confidence. Each step has order, action, system "
                        "(gmail, calendar, documents, crm, tasks, or operator), action_type (read, "
                        "analyze, draft, create, update, or follow_up), requires_approval, and "
                        "evidence_keys. Prefer 2 to 6 concrete steps."
                    ),
                },
                {"role": "user", "content": json.dumps({"goal": goal, **context}, default=str)},
            ],
            response_format={"type": "json_object"},
            temperature=0,
        )
        content = response.choices[0].message.content
        if not content:
            raise ValueError("The model returned an empty operator plan")
        plan = OperatorPlan.model_validate(json.loads(content))
        plan.goal = goal
        allowed = set(context.get("available_evidence_keys", []))
        for step in plan.steps:
            step.evidence_keys = [key for key in step.evidence_keys if key in allowed]
            if step.action_type in {"draft", "create", "update", "follow_up"}:
                step.requires_approval = True
        return plan

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
