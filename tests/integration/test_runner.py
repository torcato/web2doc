from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest

from web2doc.domain.models import (
    ClickAction,
    Effect,
    ExecutionResult,
    NavigateAction,
    ObservationDraft,
    Procedure,
    Target,
)
from web2doc.orchestration.runner import ProcedureRunner
from web2doc.policy.actions import ActionPolicy
from web2doc.storage.artifacts import ArtifactStore


@dataclass
class FakeSession:
    counter: int = 0


class FakeBrowser:
    def __init__(self, *, fail_on_write: bool = False) -> None:
        self.fail_on_write = fail_on_write
        self.executed: list[str] = []
        self.closed = False

    async def start(self, *, run_id: str, headed: bool = False) -> FakeSession:
        return FakeSession()

    async def observe(self, session: FakeSession) -> ObservationDraft:
        return ObservationDraft(
            url="http://127.0.0.1:8765/",
            title="Fixture",
            aria_snapshot=f"- heading: State {session.counter}",
            screenshot=f"png-{session.counter}".encode(),
        )

    async def execute(self, session: FakeSession, action) -> ExecutionResult:
        self.executed.append(action.kind)
        session.counter += 1
        if self.fail_on_write and action.effect is Effect.WRITE:
            raise TimeoutError("result was not observed")
        return ExecutionResult(final_url="http://127.0.0.1:8765/", message="ok")

    async def close(self, session: FakeSession) -> None:
        self.closed = True


def make_runner(repository, tmp_path: Path, project_config, browser: FakeBrowser):
    project_id, roles = repository.register_project(tmp_path, project_config)
    return ProcedureRunner(
        repository=repository,
        artifacts=ArtifactStore(tmp_path / ".web2doc"),
        browser=browser,
        policy=ActionPolicy(project_config),
        project_id=project_id,
        role_id=roles["admin"],
    )


@pytest.mark.asyncio
async def test_successful_procedure_is_awaiting_review(
    repository, tmp_path, project_config
) -> None:
    browser = FakeBrowser()
    runner = make_runner(repository, tmp_path, project_config, browser)
    procedure = Procedure(
        name="visit",
        actions=[NavigateAction(description="Open fixture", url="http://127.0.0.1:8765/")],
    )

    run_id = await runner.run(procedure)

    assert repository.get_run(run_id).status == "awaiting_review"
    assert repository.list_attempts(run_id)[0].status == "succeeded"
    assert browser.executed == ["navigate"]
    assert browser.closed


@pytest.mark.asyncio
async def test_denied_action_never_reaches_browser(repository, tmp_path, project_config) -> None:
    browser = FakeBrowser()
    runner = make_runner(repository, tmp_path, project_config, browser)
    procedure = Procedure(
        name="forbidden",
        actions=[NavigateAction(description="Leave scope", url="https://example.net/")],
    )

    run_id = await runner.run(procedure)

    assert repository.get_run(run_id).status == "paused"
    assert repository.list_attempts(run_id)[0].status == "denied"
    assert browser.executed == []


@pytest.mark.asyncio
async def test_failed_write_is_uncertain_and_not_retried(
    repository, tmp_path, project_config
) -> None:
    browser = FakeBrowser(fail_on_write=True)
    runner = make_runner(repository, tmp_path, project_config, browser)
    procedure = Procedure(
        name="write",
        actions=[
            ClickAction(
                description="Create item",
                effect=Effect.WRITE,
                operation_id="create-item",
                target=Target(role="button", name="Create"),
            )
        ],
    )

    run_id = await runner.run(procedure)

    assert repository.get_run(run_id).status == "paused"
    assert repository.list_attempts(run_id)[0].status == "uncertain"
    assert browser.executed == ["click"]
