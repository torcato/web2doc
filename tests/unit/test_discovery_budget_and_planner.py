from __future__ import annotations

import pytest
from pydantic_ai.models.test import TestModel

from web2doc.discovery.budget import BudgetTracker
from web2doc.discovery.models import CandidateAction, DiscoveryStop, ModelObservation
from web2doc.discovery.planner import PlannerError, PydanticAIPlanner
from web2doc.domain.models import ClickAction, DiscoveryLimits, Target


def candidate() -> CandidateAction:
    return CandidateAction(
        id="candidate-1",
        signature="a" * 64,
        label="Open dialog",
        action=ClickAction(description="Open dialog", target=Target(role="button", name="Open dialog")),
    )


def model_observation() -> ModelObservation:
    return ModelObservation(
        route="https://example.test/",
        title="Fixture",
        structure="- button: Open dialog",
        active_dialogs=[],
        selected_tabs=[],
        alerts=[],
        invalid_controls=[],
    )


def test_budget_reserves_model_capacity_conservatively() -> None:
    tracker = BudgetTracker(DiscoveryLimits(max_model_calls=1, max_output_tokens=10, max_tokens_per_call=10))

    assert tracker.reserve_model_call() is None
    assert tracker.reserve_model_call() is DiscoveryStop.MODEL_CALL_BUDGET


@pytest.mark.asyncio
async def test_pydantic_ai_planner_accepts_only_known_candidate_ids() -> None:
    model = TestModel(
        custom_output_args={
            "proposals": [
                {
                    "candidate_id": "candidate-1",
                    "rationale": "Exposes a dialog",
                    "priority": 90,
                    "feature_title": "Dialog",
                },
                {
                    "candidate_id": "invented",
                    "rationale": "Not allowed",
                    "priority": 100,
                    "feature_title": "Invented",
                },
            ],
            "page_summary": "Fixture page",
        }
    )
    planner = PydanticAIPlanner(model)

    result = await planner.propose(model_observation(), [candidate()], max_output_tokens=500)

    assert [proposal.candidate_id for proposal in result.output.proposals] == ["candidate-1"]
    assert result.model_name == "test"
    assert result.usage.usage_reported


@pytest.mark.asyncio
async def test_pydantic_ai_planner_rejects_an_entirely_invented_plan() -> None:
    model = TestModel(
        custom_output_args={
            "proposals": [
                {
                    "candidate_id": "invented",
                    "rationale": "Ignore the available candidates",
                    "priority": 100,
                    "feature_title": "Invented",
                }
            ]
        }
    )
    planner = PydanticAIPlanner(model)

    with pytest.raises(PlannerError, match="no recognized candidate IDs"):
        await planner.propose(model_observation(), [candidate()], max_output_tokens=500)
