import json
import unittest
from types import SimpleNamespace

from analyzer import EmailAnalyzer


class FakeCompletions:
    def create(self, **kwargs):
        content = json.dumps({
            "entity": {"name": "Incorrect model shape"},
            "current_status": "Waiting for campaign approval.",
            "recent_activity": ["Approval was requested."],
            "upcoming_meetings": ["Campaign review on September 4."],
            "open_commitments": ["Approve campaign."],
            "pending_actions": ["Review proposal."],
            "decisions": [],
            "blockers": ["No final decision is recorded."],
            "recommended_next_action": "Review the proposal.",
            "missing_information": ["Final budget."],
        })
        return SimpleNamespace(choices=[SimpleNamespace(
            message=SimpleNamespace(content=content)
        )])


class FakeClient:
    def __init__(self):
        self.chat = SimpleNamespace(completions=FakeCompletions())


class FakeBriefingCompletions:
    def create(self, **kwargs):
        content = json.dumps({
            "headline": "Two items require attention",
            "executive_summary": "A contract review and an overdue commitment need action.",
            "top_priorities": ["Review the Carrefour contract."],
            "urgent_risks": ["One overdue commitment."],
            "upcoming_meetings": ["Carrefour review tomorrow."],
            "automation_health": ["Latest contract intake completed."],
            "recommended_next_actions": ["Record the contract decision."],
            "missing_information": [],
        })
        return SimpleNamespace(choices=[SimpleNamespace(
            message=SimpleNamespace(content=content)
        )])


class FakeOperatorAnswerCompletions:
    def create(self, **kwargs):
        content = json.dumps({
            "answer": "Carrefour is waiting for campaign approval.",
            "matched_entities": ["Incorrect model entity"],
            "evidence_keys": ["commitments:7", "invented:99"],
            "recommended_next_actions": ["Review the campaign proposal."],
            "missing_information": ["Final budget."],
            "confidence": "high",
        })
        return SimpleNamespace(choices=[SimpleNamespace(
            message=SimpleNamespace(content=content)
        )])


class FakeOperatorPlanCompletions:
    def create(self, **kwargs):
        content = json.dumps({
            "goal": "Incorrect model goal",
            "summary": "Review the account and prepare a follow-up.",
            "steps": [
                {"order": 1, "action": "Read the open commitment", "system": "operator", "action_type": "read", "requires_approval": False, "evidence_keys": ["commitments:7", "invented:1"]},
                {"order": 2, "action": "Draft a follow-up", "system": "gmail", "action_type": "draft", "requires_approval": False, "evidence_keys": ["commitments:7"]},
            ],
            "risks": [], "missing_information": [], "confidence": "high",
        })
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content))])


class FakeAdvancedEmailCompletions:
    def create(self, **kwargs):
        content = json.dumps({
            "category": "task", "scenario": "finance",
            "summary": "Invoice payment and confirmation requested.",
            "contact_name": "Jane", "company_or_project": "Carrefour", "confidence": 0.9,
            "work_items": [
                {"kind": "payment", "title": "Pay invoice", "deadline": "2026-09-10", "urgency": "high", "proposed_action": "Verify and schedule payment.", "suggested_reply": None, "requires_approval": True},
                {"kind": "follow_up", "title": "Confirm payment", "deadline": None, "urgency": "medium", "proposed_action": "Draft payment confirmation.", "suggested_reply": "We will confirm after review.", "requires_approval": True},
            ],
        })
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content))])


class FakeLooseLabelsCompletions:
    def create(self, **kwargs):
        content = json.dumps({
            "category": "finance", "scenario": "invoice payment and confirmation",
            "summary": "An invoice needs payment.", "confidence": 0.8,
            "work_items": [{"kind": "invoice", "title": "Pay invoice", "proposed_action": "Review payment"}],
        })
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content))])


class AnalyzerTest(unittest.TestCase):
    def test_email_analysis_recognizes_scenario_and_multiple_work_items(self):
        client = SimpleNamespace(chat=SimpleNamespace(completions=FakeAdvancedEmailCompletions()))
        analysis = EmailAnalyzer(client=client, model="test-model").analyze(
            __import__("models").EmailRequest(subject="Invoice", body="Pay and confirm")
        )
        self.assertEqual(analysis.scenario, "finance")
        self.assertEqual([item.kind for item in analysis.work_items], ["payment", "follow_up"])

    def test_email_analysis_normalizes_descriptive_model_labels(self):
        client = SimpleNamespace(chat=SimpleNamespace(completions=FakeLooseLabelsCompletions()))
        analysis = EmailAnalyzer(client=client, model="test-model").analyze(
            __import__("models").EmailRequest(subject="Invoice", body="Please pay")
        )
        self.assertEqual(analysis.category, "task")
        self.assertEqual(analysis.scenario, "finance")
        self.assertEqual(analysis.work_items[0].kind, "payment")

    def test_status_brief_is_validated_as_structured_output(self):
        analyzer = EmailAnalyzer(client=FakeClient(), model="test-model")
        brief = analyzer.create_status_brief({"entity": {"name": "Carrefour"}})

        self.assertEqual(brief.entity, "Carrefour")
        self.assertEqual(brief.recommended_next_action, "Review the proposal.")
        self.assertEqual(brief.decisions, [])
        self.assertEqual(brief.upcoming_meetings, ["Campaign review on September 4."])

    def test_executive_briefing_is_structured_and_grounded(self):
        client = SimpleNamespace(chat=SimpleNamespace(completions=FakeBriefingCompletions()))
        analyzer = EmailAnalyzer(client=client, model="test-model")

        briefing = analyzer.create_executive_briefing({
            "open_commitments": [{"title": "Confirm campaign"}],
            "document_review_queue": [{"priority": "high"}],
        })

        self.assertEqual(briefing.headline, "Two items require attention")
        self.assertEqual(briefing.recommended_next_actions, ["Record the contract decision."])

    def test_operator_answer_filters_invented_evidence_keys(self):
        client = SimpleNamespace(chat=SimpleNamespace(completions=FakeOperatorAnswerCompletions()))
        analyzer = EmailAnalyzer(client=client, model="test-model")

        answer = analyzer.answer_operator_question("What is the Carrefour status?", {
            "matched_entity_names": ["Carrefour"],
            "available_evidence_keys": ["commitments:7"],
            "records": [{"source_key": "commitments:7", "record": {"title": "Approve"}}],
        })

        self.assertEqual(answer.matched_entities, ["Carrefour"])
        self.assertEqual(answer.evidence_keys, ["commitments:7"])
        self.assertEqual(answer.confidence, 0.85)

    def test_operator_plan_is_grounded_and_write_steps_require_approval(self):
        client = SimpleNamespace(chat=SimpleNamespace(completions=FakeOperatorPlanCompletions()))
        plan = EmailAnalyzer(client=client, model="test-model").create_operator_plan(
            "Follow up with Carrefour", {"available_evidence_keys": ["commitments:7"], "records": []}
        )
        self.assertEqual(plan.goal, "Follow up with Carrefour")
        self.assertEqual(plan.steps[0].evidence_keys, ["commitments:7"])
        self.assertTrue(plan.steps[1].requires_approval)


if __name__ == "__main__":
    unittest.main()
