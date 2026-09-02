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


class AnalyzerTest(unittest.TestCase):
    def test_status_brief_is_validated_as_structured_output(self):
        analyzer = EmailAnalyzer(client=FakeClient(), model="test-model")
        brief = analyzer.create_status_brief({"entity": {"name": "Carrefour"}})

        self.assertEqual(brief.entity, "Carrefour")
        self.assertEqual(brief.recommended_next_action, "Review the proposal.")
        self.assertEqual(brief.decisions, [])
        self.assertEqual(brief.upcoming_meetings, ["Campaign review on September 4."])


if __name__ == "__main__":
    unittest.main()
