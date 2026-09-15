from __future__ import annotations

import json

import pytest
from pydantic_ai.models.test import TestModel

from web2doc.discovery.budget import BudgetTracker
from web2doc.discovery.models import CandidateAction, DiscoveryStop, ModelObservation
from web2doc.discovery.planner import HeuristicPlanner, PlannerError, PlannerModelOutput, PydanticAIPlanner
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


@pytest.mark.asyncio
async def test_heuristic_planner_prioritizes_documentable_tasks_over_cosmetic_controls() -> None:
    labels = ["Toggle theme", "Readme", "Cancel", "Attach file", "New chat", "Chat settings"]
    candidates = [
        CandidateAction(
            id=f"candidate-{index}",
            signature=str(index) * 64,
            label=label,
            action=ClickAction(description=f"Activate {label}", target=Target(role="button", name=label)),
        )
        for index, label in enumerate(labels, start=1)
    ]

    result = await HeuristicPlanner().propose(model_observation(), candidates, max_output_tokens=500)

    ordered_labels = [labels[int(proposal.candidate_id.rsplit("-", 1)[1]) - 1] for proposal in result.output.proposals]
    assert ordered_labels == ["Chat settings", "New chat", "Attach file", "Toggle theme", "Readme", "Cancel"]


def test_budget_reserves_model_capacity_conservatively() -> None:
    tracker = BudgetTracker(DiscoveryLimits(max_model_calls=1, max_output_tokens=10, max_tokens_per_call=10))

    assert tracker.reserve_model_call() is None
    assert tracker.reserve_model_call() is DiscoveryStop.MODEL_CALL_BUDGET


def test_planner_provider_schema_avoids_expensive_serving_constraints() -> None:
    schema = json.dumps(PlannerModelOutput.model_json_schema())

    assert "maxItems" not in schema
    assert "maxLength" not in schema
    assert "minimum" not in schema
    assert "maximum" not in schema


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
            ],
            "page_summary": "Hostile plan",
        }
    )
    planner = PydanticAIPlanner(model)

    with pytest.raises(PlannerError, match="no recognized candidate IDs"):
        await planner.propose(model_observation(), [candidate()], max_output_tokens=500)


@pytest.mark.asyncio
async def test_pydantic_ai_planner_backfills_an_empty_plan_for_coverage() -> None:
    planner = PydanticAIPlanner(TestModel(custom_output_args={"proposals": [], "page_summary": "No picks"}))

    result = await planner.propose(model_observation(), [candidate()], max_output_tokens=500)

    assert [proposal.candidate_id for proposal in result.output.proposals] == ["candidate-1"]
    assert "retained for coverage" in result.output.proposals[0].rationale
