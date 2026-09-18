from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path

import pytest

from web2doc.discovery.models import ModelObservation, PlannerResult
from web2doc.discovery.planner import HeuristicPlanner
from web2doc.discovery.runner import ExplorationRunner
from web2doc.domain.models import (
    ClickAction,
    ControlDraft,
    DiscoveryLimits,
    DiscoveryMode,
    ExecutionResult,
    NavigateAction,
    ObservationDraft,
    Procedure,
    Target,
)
from web2doc.policy.actions import ActionPolicy
from web2doc.storage.artifacts import ArtifactStore


@dataclass
class FakeSession:
    state: int = 0


class DiscoveryBrowser:
    def __init__(self, *, self_loop: bool = False) -> None:
        self.self_loop = self_loop
        self.executed: list[str] = []
        self.closed = False

    async def start(self, *, run_id: str, headed: bool = False) -> FakeSession:
        return FakeSession()

    async def observe(self, session: FakeSession) -> ObservationDraft:
        controls = []
        if session.state == 1:
            controls = [ControlDraft(role="button", name="Open details")]
        return ObservationDraft(
            url=f"http://127.0.0.1:8765/state/{session.state}",
            title=f"State {session.state}",
            aria_snapshot=f"- heading: State {session.state}",
            screenshot=f"png-{session.state}".encode(),
            controls=controls,
        )

    async def execute(self, session: FakeSession, action) -> ExecutionResult:
        self.executed.append(action.kind)
        if action.kind == "navigate":
            session.state = 1
        elif not (self.self_loop and session.state == 1):
            session.state += 1
        return ExecutionResult(final_url=f"http://127.0.0.1:8765/state/{session.state}", message="ok")

    async def close(self, session: FakeSession) -> None:
        self.closed = True


class FailingPlanner:
    requires_model_budget = True

    def __init__(self) -> None:
        self.calls = 0

    async def propose(
        self,
        observation: ModelObservation,
        candidates,
        *,
        max_output_tokens: int,
    ) -> PlannerResult:
        del observation, candidates, max_output_tokens
        self.calls += 1
        raise RuntimeError("provider unavailable")


class BranchBrowser(DiscoveryBrowser):
    async def observe(self, session: FakeSession) -> ObservationDraft:
        controls = []
        if session.state == 1:
            controls = [
                ControlDraft(role="button", name="Open alpha"),
                ControlDraft(role="button", name="Open beta"),
            ]
        return ObservationDraft(
            url=f"http://127.0.0.1:8765/state/{session.state}",
            title=f"State {session.state}",
            aria_snapshot=f"- heading: State {session.state}",
            screenshot=f"png-{session.state}".encode(),
            controls=controls,
        )

    async def execute(self, session: FakeSession, action) -> ExecutionResult:
        self.executed.append(action.kind)
        if action.kind == "navigate":
            session.state = 1
        elif action.target.name == "Open alpha":
            session.state = 2
        else:
            session.state = 3
        return ExecutionResult(final_url=f"http://127.0.0.1:8765/state/{session.state}", message="ok")


class LoginBrowser(DiscoveryBrowser):
    async def observe(self, session: FakeSession) -> ObservationDraft:
        draft = await super().observe(session)
        if session.state == 1:
            return draft.model_copy(
                update={
                    "url": "http://127.0.0.1:8765/login",
                    "controls": [ControlDraft(role="textbox", name="Password", input_type="password")],
                }
            )
        return draft


class RepeatedControlBrowser(DiscoveryBrowser):
    async def observe(self, session: FakeSession) -> ObservationDraft:
        return ObservationDraft(
            url=f"http://127.0.0.1:8765/state/{session.state}",
            title=f"State {session.state}",
            aria_snapshot=f"- heading: State {session.state}",
            screenshot=f"png-{session.state}".encode(),
            controls=[ControlDraft(role="button", name="Open details")] if session.state else [],
        )


class DeepBranchBrowser(BranchBrowser):
    async def observe(self, session: FakeSession) -> ObservationDraft:
        draft = await super().observe(session)
        if session.state == 2:
            return draft.model_copy(update={"controls": [ControlDraft(role="button", name="Open deep detail")]})
        return draft


class SlowPlanner:
    requires_model_budget = True

    async def propose(
        self,
        observation: ModelObservation,
        candidates,
        *,
        max_output_tokens: int,
    ) -> PlannerResult:
        del observation, candidates, max_output_tokens
        await asyncio.sleep(10)
        raise AssertionError("the run deadline should cancel this call")


def make_runner(repository, tmp_path: Path, project_config, browser, planner):
    project_id, roles = repository.register_project(tmp_path, project_config)
    return ExplorationRunner(
        repository=repository,
        artifacts=ArtifactStore(tmp_path / ".web2doc"),
        browser=browser,
        policy=ActionPolicy(project_config),
        planner=planner,
        config=project_config,
        project_id=project_id,
        role_id=roles["admin"],
        role_name="admin",
    )


@pytest.mark.asyncio
async def test_unguided_discovery_persists_graph_feature_and_frontier(repository, tmp_path, project_config) -> None:
    browser = DiscoveryBrowser()
    runner = make_runner(repository, tmp_path, project_config, browser, HeuristicPlanner())

    run_id = await runner.run(mode=DiscoveryMode.UNGUIDED)
    report = repository.discovery_report(run_id)

    assert report["run"]["status"] == "awaiting_review"
    assert report["run"]["stop_reason"] == "frontier_exhausted"
    assert report["coverage"]["states"] == 2
    assert report["coverage"]["transitions"] == 1
    assert report["coverage"]["frontier"] == {"explored": 1}
    assert report["features"][0]["title"] == "Open details"
    assert browser.executed == ["navigate", "click"]
    assert browser.closed


@pytest.mark.asyncio
async def test_self_transition_exhausts_frontier_without_stopping_other_exploration(
    repository, tmp_path, project_config
) -> None:
    browser = DiscoveryBrowser(self_loop=True)
    runner = make_runner(repository, tmp_path, project_config, browser, HeuristicPlanner())

    run_id = await runner.run(mode=DiscoveryMode.UNGUIDED)

    assert repository.get_run(run_id).stop_reason == "frontier_exhausted"
    assert len(repository.list_attempts(run_id)) == 2


@pytest.mark.asyncio
async def test_same_action_is_not_repeated_along_a_branch(repository, tmp_path, project_config) -> None:
    browser = RepeatedControlBrowser()
    runner = make_runner(repository, tmp_path, project_config, browser, HeuristicPlanner())

    run_id = await runner.run(mode=DiscoveryMode.UNGUIDED)

    assert repository.get_run(run_id).stop_reason == "frontier_exhausted"
    assert browser.executed == ["navigate", "click"]


@pytest.mark.asyncio
async def test_saved_paths_restore_and_explore_sibling_branches(repository, tmp_path, project_config) -> None:
    browser = BranchBrowser()
    runner = make_runner(repository, tmp_path, project_config, browser, HeuristicPlanner())

    run_id = await runner.run(mode=DiscoveryMode.UNGUIDED)
    report = repository.discovery_report(run_id)

    assert {feature["title"] for feature in report["features"]} == {"Open alpha", "Open beta"}
    assert report["coverage"]["frontier"] == {"explored": 2}
    assert report["coverage"]["states"] == 3
    assert browser.executed == ["navigate", "click", "navigate", "click"]


@pytest.mark.asyncio
async def test_expired_authentication_pauses_discovery(repository, tmp_path, project_config) -> None:
    browser = LoginBrowser()
    runner = make_runner(repository, tmp_path, project_config, browser, HeuristicPlanner())

    run_id = await runner.run(mode=DiscoveryMode.UNGUIDED)

    assert repository.get_run(run_id).status == "paused"
    assert repository.get_run(run_id).stop_reason == "authentication_required"


@pytest.mark.asyncio
async def test_depth_limit_skips_deep_branch_but_finishes_shallow_siblings(
    repository, tmp_path, project_config
) -> None:
    browser = DeepBranchBrowser()
    runner = make_runner(repository, tmp_path, project_config, browser, HeuristicPlanner())

    run_id = await runner.run(
        mode=DiscoveryMode.UNGUIDED,
        limits=DiscoveryLimits(max_depth=1),
    )
    report = repository.discovery_report(run_id)

    assert report["run"]["stop_reason"] == "depth_budget_exhausted"
    assert report["coverage"]["frontier"] == {"explored": 2, "skipped": 1}
    assert browser.executed == ["navigate", "click", "navigate", "click"]


@pytest.mark.asyncio
async def test_wall_clock_budget_interrupts_stalled_planner(repository, tmp_path, project_config) -> None:
    browser = DiscoveryBrowser()
    runner = make_runner(repository, tmp_path, project_config, browser, SlowPlanner())

    run_id = await runner.run(
        mode=DiscoveryMode.UNGUIDED,
        limits=DiscoveryLimits(max_duration_seconds=1, model_retries=0),
    )

    assert repository.get_run(run_id).stop_reason == "time_budget_exhausted"
    assert repository.discovery_report(run_id)["coverage"]["model_calls"] == 1


@pytest.mark.asyncio
async def test_action_budget_stops_before_second_action(repository, tmp_path, project_config) -> None:
    browser = DiscoveryBrowser()
    runner = make_runner(repository, tmp_path, project_config, browser, HeuristicPlanner())
    limits = DiscoveryLimits(max_actions=1)

    run_id = await runner.run(mode=DiscoveryMode.UNGUIDED, limits=limits)

    assert repository.get_run(run_id).stop_reason == "action_budget_exhausted"
    assert browser.executed == ["navigate"]


@pytest.mark.asyncio
async def test_budget_exhausted_discovery_can_resume_existing_frontier(
    repository, tmp_path, project_config
) -> None:
    browser = DiscoveryBrowser()
    runner = make_runner(repository, tmp_path, project_config, browser, HeuristicPlanner())
    run_id = await runner.run(
        mode=DiscoveryMode.UNGUIDED,
        limits=DiscoveryLimits(max_actions=1),
    )

    resumed_run_id = await runner.resume(
        run_id,
        additional_limits=DiscoveryLimits(max_actions=5),
    )
    report = repository.discovery_report(run_id)

    assert resumed_run_id == run_id
    assert report["run"]["stop_reason"] == "frontier_exhausted"
    assert report["coverage"]["frontier"] == {"explored": 1}
    assert report["coverage"]["states"] == 2
    assert browser.executed == ["navigate", "navigate", "click"]


@pytest.mark.asyncio
async def test_planner_retries_are_bounded_and_usage_is_conservative(repository, tmp_path, project_config) -> None:
    browser = DiscoveryBrowser()
    planner = FailingPlanner()
    runner = make_runner(repository, tmp_path, project_config, browser, planner)
    limits = DiscoveryLimits(model_retries=2, max_model_calls=3)

    run_id = await runner.run(mode=DiscoveryMode.UNGUIDED, limits=limits)
    report = repository.discovery_report(run_id)

    assert planner.calls == 3
    assert report["run"]["status"] == "paused"
    assert str(report["run"]["stop_reason"]).startswith("planner_failed")
    assert report["coverage"]["model_calls"] == 3
    assert report["coverage"]["output_tokens"] == 6_000


@pytest.mark.asyncio
async def test_supplied_mode_maps_each_step_without_calling_model(repository, tmp_path, project_config) -> None:
    browser = DiscoveryBrowser()
    planner = FailingPlanner()
    runner = make_runner(repository, tmp_path, project_config, browser, planner)
    procedure = Procedure(
        name="Known path",
        actions=[
            NavigateAction(description="Open known page", url="http://127.0.0.1:8765/known"),
            ClickAction(description="Open details", target=Target(role="button", name="Open details")),
        ],
    )

    run_id = await runner.run(mode=DiscoveryMode.SUPPLIED, supplied_procedure=procedure)

    assert repository.get_run(run_id).stop_reason == "supplied_workflow_complete"
    assert planner.calls == 0
    assert repository.discovery_report(run_id)["coverage"]["transitions"] == 1
