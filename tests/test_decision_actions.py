import tempfile
import unittest
from pathlib import Path

import main
from database import Database
from models import (
    ActionStatus,
    DecisionProposalUpdateRequest,
    DecisionRequest,
    EmailAnalysis,
    EmailRequest,
    EmailWorkItem,
)


class DecisionActionTest(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.original_database = main.database
        main.database = Database(str(Path(self.tempdir.name) / "test.db"))
        main.database.init()

    def tearDown(self):
        main.database = self.original_database
        self.tempdir.cleanup()

    def test_approved_decision_proposal_is_recorded_for_linked_entity(self):
        _, commitment_id, action_id = main.database.save_analysis(
            EmailRequest(subject="Approve launch", body="Should Atlas launch?"),
            EmailAnalysis(
                category="decision", scenario="approval", summary="Launch approval requested.",
                company_or_project="Atlas",
                work_items=[EmailWorkItem(
                    kind="decision", title="Atlas launch",
                    proposed_action="Decide whether Atlas should launch.",
                )],
            ),
        )

        main.update_decision_proposal(action_id, DecisionProposalUpdateRequest(
            title="Atlas launch", decision="Launch on Monday.",
            rationale="The pilot targets were met.",
        ))
        main.approve_action(action_id, DecisionRequest(note="Approved by operator"))
        finished = main.execute_action(action_id)

        self.assertEqual(finished["status"], ActionStatus.EXECUTED.value)
        entity = main.database.get_entity("Atlas")
        context = main.database.entity_context(entity["id"])
        self.assertEqual(context["decisions"][0]["decision"], "Launch on Monday.")
        self.assertEqual(context["decisions"][0]["source_email_id"],
                         main.database.list_rows("commitments")[0]["email_id"])
        self.assertEqual(main.database.list_rows("commitments")[0]["id"], commitment_id)


if __name__ == "__main__":
    unittest.main()
