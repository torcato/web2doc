from __future__ import annotations

import base64
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from web2doc.domain.models import (
    ClickAction,
    Effect,
    ExecutionResult,
    NavigateAction,
    ObservationDraft,
    ProjectConfig,
    Target,
)
from web2doc.policy.actions import ActionPolicy
from web2doc.storage.artifacts import ArtifactStore
from web2doc.storage.repository import Repository
from web2doc.verification.models import (
    EnvironmentJsonPredicate,
    FixtureReceiptDraft,
    PredicateResultDraft,
    PredicateStatus,
    VisibleTextPredicate,
    WorkflowDefinition,
    WorkflowStep,
)
from web2doc.verification.runner import VerificationRunner


@dataclass
class FakeEnvironment:
    name: str = "fake"
    items: list[str] = field(default_factory=list)
    prepare_count: int = 0
    reset_count: int = 0

    async def prepare(self, scenario: str, inputs: dict[str, str]) -> FixtureReceiptDraft:
        self.prepare_count += 1
        self.items.clear()
        return FixtureReceiptDraft(adapter_name=self.name, scenario=scenario, payload={"inputs": inputs})

    async def check(self, predicate: EnvironmentJsonPredicate, receipt: FixtureReceiptDraft) -> PredicateResultDraft:
        del receipt
        found = predicate.expected in self.items
        passed = found if predicate.operator == "contains" else not found
        return PredicateResultDraft(
            status=PredicateStatus.PASSED if passed else PredicateStatus.FAILED,
            message=f"item membership matched: {passed}",
            observed=list(self.items),
        )

    async def reset(self, receipt: FixtureReceiptDraft) -> None:
        del receipt
        self.reset_count += 1
        self.items.clear()


@dataclass
class FakeSession:
    state: int = 0


class VerificationBrowser:
    def __init__(self, environment: FakeEnvironment | None = None, *, crash_after_write: bool = False) -> None:
        self.environment = environment
        self.crash_after_write = crash_after_write
        self.executed: list[str] = []

    async def start(self, *, run_id: str, headed: bool = False) -> FakeSession:
        return FakeSession()

    async def observe(self, session: FakeSession) -> ObservationDraft:
        return ObservationDraft(
            url="http://127.0.0.1:8765/",
            title="Fixture",
            aria_snapshot="- status: Success" if session.state else "- heading: Items",
            screenshot=base64.b64decode(
                "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
            ),
        )

    async def execute(self, session: FakeSession, action) -> ExecutionResult:
        self.executed.append(action.kind)
        session.state += 1
        if action.effect is Effect.WRITE and self.environment is not None:
            self.environment.items.append("Only once")
            if self.crash_after_write:
                raise RuntimeError("worker disappeared after submission")
        return ExecutionResult(final_url="http://127.0.0.1:8765/", message="ok")

    async def close(self, session: FakeSession) -> None:
        del session


class MissingTargetBrowser(VerificationBrowser):
    async def execute(self, session: FakeSession, action) -> ExecutionResult:
        if action.kind == "click":
            self.executed.append(action.kind)
            raise RuntimeError("target was not found")
        return await super().execute(session, action)


def make_runner(
    repository: Repository,
    tmp_path: Path,
    config: ProjectConfig,
    browser: VerificationBrowser,
    environment: FakeEnvironment | None,
) -> tuple[VerificationRunner[FakeSession], str, str]:
    project_id, roles = repository.register_project(tmp_path, config)
    return (
        VerificationRunner(
            repository=repository,
            artifacts=ArtifactStore(tmp_path / ".web2doc"),
            browser=browser,
            policy=ActionPolicy(config),
            environment=environment,
            project_id=project_id,
            role_id=roles["admin"],
            role_name="admin",
            base_url=str(config.base_url),
        ),
        project_id,
        roles["admin"],
    )


@pytest.mark.asyncio
async def test_success_looking_ui_does_not_override_failed_outcome(
    repository: Repository, tmp_path: Path, project_config: ProjectConfig
) -> None:
    runner, project_id, role_id = make_runner(repository, tmp_path, project_config, VerificationBrowser(), None)
    definition = WorkflowDefinition(
        workflow_key="false-success",
        title="Reject false success",
        goal="Require the real outcome",
        role="admin",
        steps=[
            WorkflowStep(
                action=NavigateAction(description="Open", url=str(project_config.base_url)),
                expected=[VisibleTextPredicate(text="Record persisted")],
            )
        ],
        final_outcomes=[VisibleTextPredicate(text="Success")],
    )
    revision = repository.add_workflow_revision(project_id=project_id, role_id=role_id, definition=definition)

    verification_id = await runner.run(revision)

    report = repository.verification_report(verification_id)
    assert report["status"] == "failed"
    assert report["predicates"][0]["status"] == "failed"


@pytest.mark.asyncio
async def test_uncertain_write_is_reconciled_without_duplicate_submission(
    repository: Repository, tmp_path: Path, project_config: ProjectConfig
) -> None:
    environment = FakeEnvironment()
    first_browser = VerificationBrowser(environment, crash_after_write=True)
    first_runner, project_id, role_id = make_runner(repository, tmp_path, project_config, first_browser, environment)
    outcome = EnvironmentJsonPredicate(path="items", operator="contains", expected="Only once")
    definition = WorkflowDefinition(
        workflow_key="reconcile-write",
        title="Reconcile write",
        goal="Avoid duplicate writes after a crash",
        role="admin",
        steps=[
            WorkflowStep(
                action=ClickAction(
                    description="Create",
                    effect="write",
                    operation_id="create-item",
                    target=Target(role="button", name="Create"),
                ),
                expected=[outcome],
            )
        ],
        final_outcomes=[outcome],
    )
    revision = repository.add_workflow_revision(project_id=project_id, role_id=role_id, definition=definition)
    first_id = await first_runner.run(revision)
    assert repository.verification_report(first_id)["status"] == "inconclusive"
    assert environment.items == ["Only once"]
    assert environment.reset_count == 0

    second_browser = VerificationBrowser(environment)
    second_runner, _project_id, _role_id = make_runner(
        repository, tmp_path, project_config, second_browser, environment
    )
    second_id = await second_runner.run(revision)

    assert repository.verification_report(second_id)["status"] == "passed"
    assert second_browser.executed == ["navigate"]
    second_run = repository.verification_report(second_id)["run_id"]
    assert repository.list_attempts(str(second_run))[-1].status == "reconciled"
    assert environment.prepare_count == 1
    assert environment.reset_count == 1


@pytest.mark.asyncio
async def test_broken_authentication_prerequisite_stops_before_workflow_actions(
    repository: Repository, tmp_path: Path, project_config: ProjectConfig
) -> None:
    browser = VerificationBrowser()
    runner, project_id, role_id = make_runner(repository, tmp_path, project_config, browser, None)
    definition = WorkflowDefinition(
        workflow_key="requires-auth",
        title="Authenticated action",
        goal="Use a signed-in session",
        role="admin",
        prerequisites=[VisibleTextPredicate(text="Signed in as admin")],
        steps=[WorkflowStep(action=ClickAction(description="Continue", target=Target(role="button", name="Continue")))],
        final_outcomes=[VisibleTextPredicate(text="Done")],
    )
    revision = repository.add_workflow_revision(project_id=project_id, role_id=role_id, definition=definition)

    verification_id = await runner.run(revision)

    assert repository.verification_report(verification_id)["status"] == "failed"
    assert browser.executed == ["navigate"]


@pytest.mark.asyncio
async def test_workflow_must_be_reverified_after_target_recovers(
    repository: Repository, tmp_path: Path, project_config: ProjectConfig
) -> None:
    failing_runner, project_id, role_id = make_runner(
        repository, tmp_path, project_config, MissingTargetBrowser(), None
    )
    definition = WorkflowDefinition(
        workflow_key="recovered-target",
        title="Recovered target",
        goal="Verify the target after its label is repaired",
        role="admin",
        steps=[WorkflowStep(action=ClickAction(description="Continue", target=Target(role="button", name="Continue")))],
        final_outcomes=[VisibleTextPredicate(text="Success")],
    )
    revision = repository.add_workflow_revision(project_id=project_id, role_id=role_id, definition=definition)
    failed_id = await failing_runner.run(revision)
    assert repository.verification_report(failed_id)["status"] == "failed"

    recovered_browser = VerificationBrowser()
    recovered_runner, _project_id, _role_id = make_runner(repository, tmp_path, project_config, recovered_browser, None)
    passed_id = await recovered_runner.run(revision)

    assert repository.verification_report(passed_id)["status"] == "passed"
    assert recovered_browser.executed == ["navigate", "click"]
