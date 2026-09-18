from __future__ import annotations

import socket
import threading
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
import uvicorn
from playwright.async_api import Error as PlaywrightError

from tests.fixtures.site_app import app
from web2doc.browser.base import BrowserExecutionError
from web2doc.browser.playwright import (
    AmbiguousTargetError,
    PlaywrightBrowser,
    ScopeViolationError,
    TargetNotFoundError,
)
from web2doc.discovery.planner import HeuristicPlanner
from web2doc.discovery.runner import ExplorationRunner
from web2doc.domain.models import (
    ClickAction,
    DiscoveryLimits,
    DiscoveryMode,
    FillAction,
    NavigateAction,
    ObservationDraft,
    PolicyConfig,
    Procedure,
    ProjectConfig,
    RoleConfig,
    Target,
)
from web2doc.orchestration.runner import ProcedureRunner
from web2doc.policy.actions import ActionPolicy
from web2doc.storage.artifacts import ArtifactStore
from web2doc.storage.database import upgrade_database
from web2doc.storage.repository import Repository
from web2doc.verification.environment import HttpJsonEnvironmentAdapter
from web2doc.verification.models import (
    EnvironmentJsonPredicate,
    TitlePredicate,
    UrlPredicate,
    VisibleTextPredicate,
    WorkflowDefinition,
    WorkflowStep,
)
from web2doc.verification.runner import VerificationRunner


def benchmark_workflows(site_url: str) -> list[WorkflowDefinition]:
    seed = {"seed": "Seed item"}
    return [
        WorkflowDefinition(
            workflow_key="view-items",
            title="View items",
            goal="Open the item list",
            role="admin",
            steps=[WorkflowStep(action=NavigateAction(description="Open items", url=f"{site_url}/"))],
            final_outcomes=[TitlePredicate(expected="Fixture")],
        ),
        WorkflowDefinition(
            workflow_key="create-item",
            title="Create item",
            goal="Persist a new item",
            role="admin",
            test_inputs={"name": "Benchmark item"},
            steps=[
                WorkflowStep(
                    action=FillAction(description="Enter name", target=Target(label="Item name"), value="{{name}}")
                ),
                WorkflowStep(
                    action=ClickAction(
                        description="Create",
                        effect="write",
                        operation_id="create-item",
                        target=Target(role="button", name="Create"),
                    ),
                    expected=[EnvironmentJsonPredicate(path="items", operator="contains", expected="Benchmark item")],
                ),
            ],
            final_outcomes=[TitlePredicate(expected="Created")],
        ),
        WorkflowDefinition(
            workflow_key="validation-error",
            title="See validation error",
            goal="Reject an empty required name",
            role="admin",
            steps=[
                WorkflowStep(action=NavigateAction(description="Open validation", url=f"{site_url}/validation")),
                WorkflowStep(
                    action=ClickAction(
                        description="Validate empty form",
                        effect="write",
                        operation_id="validate-item",
                        target=Target(role="button", name="Validate"),
                    ),
                    expected=[VisibleTextPredicate(text="Name is required")],
                ),
            ],
            final_outcomes=[EnvironmentJsonPredicate(path="items", expected=[])],
        ),
        WorkflowDefinition(
            workflow_key="edit-item",
            title="Edit item",
            goal="Change an existing item",
            role="admin",
            scenario="existing-item",
            test_inputs={**seed, "updated": "Updated item"},
            steps=[
                WorkflowStep(action=NavigateAction(description="Open edit form", url=f"{site_url}/items/edit")),
                WorkflowStep(
                    action=FillAction(description="Change name", target=Target(label="Item name"), value="{{updated}}")
                ),
                WorkflowStep(
                    action=ClickAction(
                        description="Save",
                        effect="write",
                        operation_id="edit-item",
                        target=Target(role="button", name="Save"),
                    ),
                    expected=[EnvironmentJsonPredicate(path="items", operator="contains", expected="Updated item")],
                ),
            ],
            final_outcomes=[TitlePredicate(expected="Updated")],
        ),
        WorkflowDefinition(
            workflow_key="delete-item",
            title="Delete item",
            goal="Delete an existing item",
            role="admin",
            scenario="existing-item",
            test_inputs=seed,
            steps=[
                WorkflowStep(action=NavigateAction(description="Open delete form", url=f"{site_url}/items/delete")),
                WorkflowStep(
                    action=ClickAction(
                        description="Delete",
                        effect="write",
                        operation_id="delete-item",
                        target=Target(role="button", name="Delete"),
                    ),
                    expected=[EnvironmentJsonPredicate(path="items", expected=[])],
                ),
            ],
            final_outcomes=[TitlePredicate(expected="Deleted")],
        ),
        WorkflowDefinition(
            workflow_key="search-items",
            title="Search items",
            goal="Find a seeded item",
            role="admin",
            scenario="existing-item",
            test_inputs=seed,
            steps=[
                WorkflowStep(
                    action=NavigateAction(description="Search", url=f"{site_url}/search?q=Seed"),
                    expected=[VisibleTextPredicate(text="Seed item")],
                )
            ],
            final_outcomes=[UrlPredicate(expected="/search", match="path")],
        ),
        WorkflowDefinition(
            workflow_key="open-dialog",
            title="Open dialog",
            goal="Open the help dialog",
            role="admin",
            steps=[
                WorkflowStep(action=NavigateAction(description="Open page", url=f"{site_url}/dialog")),
                WorkflowStep(
                    action=ClickAction(description="Open help", target=Target(role="button", name="Open help")),
                    expected=[VisibleTextPredicate(text="Dialog content")],
                ),
            ],
            final_outcomes=[TitlePredicate(expected="Dialog")],
        ),
        WorkflowDefinition(
            workflow_key="select-tab",
            title="Select settings tab",
            goal="Show settings",
            role="admin",
            steps=[
                WorkflowStep(action=NavigateAction(description="Open tabs", url=f"{site_url}/tabs")),
                WorkflowStep(
                    action=ClickAction(description="Select settings", target=Target(role="tab", name="Settings")),
                    expected=[VisibleTextPredicate(text="Settings panel")],
                ),
            ],
            final_outcomes=[TitlePredicate(expected="Tabs")],
        ),
        WorkflowDefinition(
            workflow_key="access-denied",
            title="Reject anonymous admin access",
            goal="Confirm restricted access",
            role="admin",
            steps=[
                WorkflowStep(
                    action=NavigateAction(description="Open admin", url=f"{site_url}/admin"),
                    expected=[VisibleTextPredicate(text="Access denied")],
                )
            ],
            final_outcomes=[TitlePredicate(expected="Access denied")],
        ),
        WorkflowDefinition(
            workflow_key="failed-save",
            title="Report failed save",
            goal="Confirm a failed save does not persist data",
            role="admin",
            scenario="save-failure",
            test_inputs={"name": "Must not persist"},
            steps=[
                WorkflowStep(
                    action=FillAction(description="Enter name", target=Target(label="Item name"), value="{{name}}")
                ),
                WorkflowStep(
                    action=ClickAction(
                        description="Try save",
                        effect="write",
                        operation_id="create-item",
                        target=Target(role="button", name="Create"),
                    ),
                    expected=[
                        VisibleTextPredicate(text="Save failed"),
                        EnvironmentJsonPredicate(path="items", expected=[]),
                    ],
                ),
            ],
            final_outcomes=[EnvironmentJsonPredicate(path="items", expected=[])],
        ),
    ]


@pytest.mark.asyncio
async def test_observation_retries_while_navigation_replaces_document(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = ProjectConfig(
        name="browser test",
        base_url="https://example.test",
        allowed_origins={"https://example.test"},
        roles=[RoleConfig(name="admin")],
    )
    browser = PlaywrightBrowser(project_root=tmp_path, config=config, role=config.role("admin"))
    expected = ObservationDraft(
        url="https://example.test/dashboard",
        title="Dashboard",
        aria_snapshot='- heading "Dashboard"',
        screenshot=b"png",
    )
    attempts = 0

    async def observe_once(_session: Any) -> ObservationDraft:
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise PlaywrightError('Locator.aria_snapshot: Selector "body" does not match any element')
        return expected

    monkeypatch.setattr(browser, "_observe_once", observe_once)

    session: Any = SimpleNamespace(page=SimpleNamespace(url="https://example.test/dashboard"))
    observed = await browser.observe(session)

    assert observed is expected
    assert attempts == 3


@pytest.mark.asyncio
async def test_observation_reports_page_that_never_stabilizes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = ProjectConfig(
        name="browser test",
        base_url="https://example.test",
        allowed_origins={"https://example.test"},
        roles=[RoleConfig(name="admin")],
    )
    browser = PlaywrightBrowser(project_root=tmp_path, config=config, role=config.role("admin"))

    async def observe_once(_session: Any) -> ObservationDraft:
        raise PlaywrightError('Locator.aria_snapshot: Selector "body" does not match any element')

    monkeypatch.setattr(browser, "_observe_once", observe_once)

    session: Any = SimpleNamespace(page=SimpleNamespace(url="https://example.test/dashboard"))
    with pytest.raises(BrowserExecutionError, match="page did not become observable.*dashboard"):
        await browser.observe(session)


def unused_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


@pytest.fixture
def site_url() -> str:
    port = unused_port()
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    url = f"http://127.0.0.1:{port}"
    for _ in range(100):
        try:
            if httpx.get(f"{url}/__state", timeout=0.1).status_code == 200:
                break
        except httpx.HTTPError:
            time.sleep(0.02)
    else:
        server.should_exit = True
        thread.join(timeout=2)
        raise RuntimeError("fixture server did not start")
    httpx.post(f"{url}/__reset")
    try:
        yield url
    finally:
        server.should_exit = True
        thread.join(timeout=5)


@pytest.mark.browser
@pytest.mark.asyncio
async def test_playwright_executes_semantic_workflow(tmp_path: Path, site_url: str) -> None:
    config = ProjectConfig(
        name="browser test",
        base_url=site_url,
        allowed_origins={site_url},
        roles=[RoleConfig(name="admin")],
        policy=PolicyConfig(allowed_write_operations={"create-item"}),
    )
    browser = PlaywrightBrowser(project_root=tmp_path, config=config, role=config.role("admin"))
    try:
        session = await browser.start(run_id="browser-test")
    except Exception as exc:
        if "Executable doesn't exist" in str(exc):
            pytest.skip("Playwright Chromium is not installed")
        raise

    try:
        await browser.execute(
            session,
            NavigateAction(description="Open fixture", url=f"{site_url}/"),
        )
        observation = await browser.observe(session)
        assert "Items" in observation.aria_snapshot
        assert observation.screenshot.startswith(b"\x89PNG")

        await browser.execute(
            session,
            FillAction(
                description="Name item",
                target=Target(label="Item name"),
                value="Evidence item",
            ),
        )
        await browser.execute(
            session,
            ClickAction(
                description="Create item",
                effect="write",
                operation_id="create-item",
                target=Target(role="button", name="Create"),
            ),
        )
        async with httpx.AsyncClient() as client:
            assert (await client.get(f"{site_url}/__state")).json() == {"items": ["Evidence item"]}
    finally:
        await browser.close(session)


@pytest.mark.browser
@pytest.mark.asyncio
async def test_external_popup_is_blocked_and_reported(tmp_path: Path, site_url: str) -> None:
    config = ProjectConfig(
        name="browser test",
        base_url=site_url,
        allowed_origins={site_url},
        roles=[RoleConfig(name="admin")],
    )
    browser = PlaywrightBrowser(project_root=tmp_path, config=config, role=config.role("admin"))
    session = await browser.start(run_id="scope-test")
    try:
        await browser.execute(
            session,
            NavigateAction(description="Open fixture", url=f"{site_url}/"),
        )
        with pytest.raises(ScopeViolationError, match="outside.example"):
            await browser.execute(
                session,
                ClickAction(
                    description="Open external help",
                    target=Target(role="link", name="External help"),
                ),
            )
    finally:
        await browser.close(session)


@pytest.mark.browser
@pytest.mark.asyncio
async def test_external_redirect_is_blocked_and_reported(tmp_path: Path, site_url: str) -> None:
    config = ProjectConfig(
        name="browser test",
        base_url=site_url,
        allowed_origins={site_url},
        roles=[RoleConfig(name="admin")],
    )
    browser = PlaywrightBrowser(project_root=tmp_path, config=config, role=config.role("admin"))
    session = await browser.start(run_id="redirect-scope-test")
    try:
        with pytest.raises(ScopeViolationError, match="outside.example"):
            await browser.execute(
                session,
                NavigateAction(description="Follow redirect", url=f"{site_url}/external-redirect"),
            )
    finally:
        await browser.close(session)


@pytest.mark.browser
@pytest.mark.asyncio
async def test_real_browser_runner_persists_evidence(tmp_path: Path, site_url: str) -> None:
    config = ProjectConfig(
        name="end-to-end",
        base_url=site_url,
        allowed_origins={site_url},
        roles=[RoleConfig(name="admin")],
        policy=PolicyConfig(allowed_write_operations={"create-item"}),
    )
    database = tmp_path / ".web2doc/state.sqlite3"
    upgrade_database(database)
    repository = Repository(database)
    project_id, roles = repository.register_project(tmp_path, config)
    browser = PlaywrightBrowser(project_root=tmp_path, config=config, role=config.role("admin"))
    runner = ProcedureRunner(
        repository=repository,
        artifacts=ArtifactStore(tmp_path / ".web2doc"),
        browser=browser,
        policy=ActionPolicy(config),
        project_id=project_id,
        role_id=roles["admin"],
    )
    procedure = Procedure(
        name="Create fixture item",
        actions=[
            NavigateAction(description="Open fixture", url=f"{site_url}/"),
            FillAction(
                description="Name item",
                target=Target(label="Item name"),
                value="Persisted item",
            ),
            ClickAction(
                description="Create item",
                effect="write",
                operation_id="create-item",
                target=Target(role="button", name="Create"),
            ),
        ],
    )
    try:
        run_id = await runner.run(procedure)
        summary = repository.run_summary(run_id)
        assert summary["status"] == "awaiting_review"
        assert [attempt["status"] for attempt in summary["attempts"]] == [
            "succeeded",
            "succeeded",
            "succeeded",
        ]
        assert len(list((tmp_path / f".web2doc/artifacts/{run_id}").rglob("*.png"))) == 4
        assert (tmp_path / f".web2doc/private/traces/{run_id}.zip").is_file()
        async with httpx.AsyncClient() as client:
            assert (await client.get(f"{site_url}/__state")).json() == {"items": ["Persisted item"]}
    finally:
        repository.close()


@pytest.mark.browser
@pytest.mark.asyncio
async def test_real_browser_verifies_workflow_outcomes_and_resets_fixture(tmp_path: Path, site_url: str) -> None:
    config = ProjectConfig(
        name="verification",
        base_url=site_url,
        allowed_origins={site_url},
        roles=[RoleConfig(name="admin")],
        policy=PolicyConfig(allowed_write_operations={"create-item"}),
    )
    database = tmp_path / ".web2doc/state.sqlite3"
    upgrade_database(database)
    repository = Repository(database)
    project_id, roles = repository.register_project(tmp_path, config)
    definition = WorkflowDefinition(
        workflow_key="create-item",
        title="Create an item",
        goal="Create an item and confirm its persisted state",
        role="admin",
        test_inputs={"name": "Verified item"},
        steps=[
            WorkflowStep(
                action=FillAction(
                    description="Enter item name",
                    target=Target(label="Item name"),
                    value="{{name}}",
                )
            ),
            WorkflowStep(
                action=ClickAction(
                    description="Create item",
                    effect="write",
                    operation_id="create-item",
                    target=Target(role="button", name="Create"),
                ),
                expected=[
                    VisibleTextPredicate(text="Verified item"),
                    EnvironmentJsonPredicate(path="items", operator="contains", expected="Verified item"),
                ],
            ),
        ],
        final_outcomes=[TitlePredicate(expected="Created")],
    )
    revision = repository.add_workflow_revision(
        project_id=project_id,
        role_id=roles["admin"],
        definition=definition,
    )
    runner = VerificationRunner(
        repository=repository,
        artifacts=ArtifactStore(tmp_path / ".web2doc"),
        browser=PlaywrightBrowser(project_root=tmp_path, config=config, role=config.role("admin")),
        policy=ActionPolicy(config),
        environment=HttpJsonEnvironmentAdapter(base_url=site_url, allowed_origins={site_url}),
        project_id=project_id,
        role_id=roles["admin"],
        role_name="admin",
        base_url=site_url,
    )
    try:
        verification_id = await runner.run(revision)
        report = repository.verification_report(verification_id)
        assert report["status"] == "passed"
        assert {result["status"] for result in report["predicates"]} == {"passed"}
        async with httpx.AsyncClient() as client:
            assert (await client.get(f"{site_url}/__state")).json() == {"items": []}
    finally:
        repository.close()


@pytest.mark.browser
@pytest.mark.asyncio
async def test_ten_workflow_benchmark_replays_three_times(tmp_path: Path, site_url: str) -> None:
    config = ProjectConfig(
        name="benchmark",
        base_url=site_url,
        allowed_origins={site_url},
        roles=[RoleConfig(name="admin")],
        policy=PolicyConfig(allowed_write_operations={"create-item", "validate-item", "edit-item", "delete-item"}),
    )
    database = tmp_path / ".web2doc/state.sqlite3"
    upgrade_database(database)
    repository = Repository(database)
    project_id, roles = repository.register_project(tmp_path, config)
    try:
        revisions = [
            repository.add_workflow_revision(
                project_id=project_id,
                role_id=roles["admin"],
                definition=definition,
            )
            for definition in benchmark_workflows(site_url)
        ]
        results: list[str] = []
        for _repeat in range(3):
            for revision in revisions:
                runner = VerificationRunner(
                    repository=repository,
                    artifacts=ArtifactStore(tmp_path / ".web2doc"),
                    browser=PlaywrightBrowser(project_root=tmp_path, config=config, role=config.role("admin")),
                    policy=ActionPolicy(config),
                    environment=HttpJsonEnvironmentAdapter(base_url=site_url, allowed_origins={site_url}),
                    project_id=project_id,
                    role_id=roles["admin"],
                    role_name="admin",
                    base_url=site_url,
                )
                verification_id = await runner.run(revision)
                results.append(str(repository.verification_report(verification_id)["status"]))
        assert len(results) == 30
        assert set(results) == {"passed"}
    finally:
        repository.close()


@pytest.mark.browser
@pytest.mark.asyncio
async def test_authentication_state_is_isolated_by_role(tmp_path: Path, site_url: str) -> None:
    config = ProjectConfig(
        name="auth test",
        base_url=site_url,
        allowed_origins={site_url},
        roles=[
            RoleConfig(name="admin", storage_state=".web2doc/private/auth/admin.json"),
            RoleConfig(name="member", storage_state=".web2doc/private/auth/member.json"),
        ],
    )

    for role_name in ("admin", "member"):
        browser = PlaywrightBrowser(
            project_root=tmp_path,
            config=config,
            role=config.role(role_name),
        )
        session = await browser.start(run_id=f"auth-{role_name}")
        try:
            await browser.execute(
                session,
                NavigateAction(
                    description=f"Log in as {role_name}",
                    url=f"{site_url}/login/{role_name}",
                ),
            )
            path = await browser.save_authentication(session)
            assert path.name == f"{role_name}.json"
        finally:
            await browser.close(session)

    admin_browser = PlaywrightBrowser(
        project_root=tmp_path,
        config=config,
        role=config.role("admin"),
    )
    admin_session = await admin_browser.start(run_id="auth-check")
    try:
        await admin_browser.execute(
            admin_session,
            NavigateAction(description="Check role", url=f"{site_url}/whoami"),
        )
        assert "Role: admin" in (await admin_browser.observe(admin_session)).aria_snapshot
    finally:
        await admin_browser.close(admin_session)


@pytest.mark.browser
@pytest.mark.asyncio
async def test_ambiguous_target_is_rejected(tmp_path: Path, site_url: str) -> None:
    config = ProjectConfig(
        name="browser test",
        base_url=site_url,
        allowed_origins={site_url},
        roles=[RoleConfig(name="admin")],
    )
    browser = PlaywrightBrowser(project_root=tmp_path, config=config, role=config.role("admin"))
    try:
        session = await browser.start(run_id="ambiguous-test")
    except Exception as exc:
        if "Executable doesn't exist" in str(exc):
            pytest.skip("Playwright Chromium is not installed")
        raise
    try:
        await browser.execute(
            session,
            NavigateAction(description="Open fixture", url=f"{site_url}/"),
        )
        with pytest.raises(AmbiguousTargetError):
            await browser.execute(
                session,
                ClickAction(description="Ambiguous", target=Target(css="body *")),
            )
    finally:
        await browser.close(session)


@pytest.mark.browser
@pytest.mark.asyncio
async def test_observation_does_not_invent_names_for_unnamed_controls(
    tmp_path: Path,
) -> None:
    site_url = "https://example.test"
    config = ProjectConfig(
        name="browser test",
        base_url=site_url,
        allowed_origins={site_url},
        roles=[RoleConfig(name="admin")],
    )
    browser = PlaywrightBrowser(project_root=tmp_path, config=config, role=config.role("admin"))
    session = await browser.start(run_id="unnamed-control-test")
    try:
        await session.page.set_content(
            '<button id="unnamed"></button><button aria-label="Open menu"></button>'
        )

        observation = await browser.observe(session)

        assert [(control.role, control.name) for control in observation.controls] == [
            ("button", ""),
            ("button", "Open menu"),
        ]
    finally:
        await browser.close(session)


@pytest.mark.browser
@pytest.mark.asyncio
async def test_delayed_target_is_awaited_and_missing_target_is_rejected(tmp_path: Path, site_url: str) -> None:
    config = ProjectConfig(
        name="browser test",
        base_url=site_url,
        allowed_origins={site_url},
        roles=[RoleConfig(name="admin")],
    )
    browser = PlaywrightBrowser(project_root=tmp_path, config=config, role=config.role("admin"))
    session = await browser.start(run_id="target-wait-test")
    try:
        await browser.execute(
            session,
            NavigateAction(description="Open fixture", url=f"{site_url}/"),
        )
        await browser.execute(
            session,
            ClickAction(
                description="Wait for delayed action",
                target=Target(role="button", name="Delayed action"),
                timeout_ms=2_000,
            ),
        )
        with pytest.raises(TargetNotFoundError):
            await browser.execute(
                session,
                ClickAction(
                    description="Missing target",
                    target=Target(role="button", name="Never appears"),
                    timeout_ms=100,
                ),
            )
    finally:
        await browser.close(session)


@pytest.mark.browser
@pytest.mark.asyncio
async def test_real_browser_discovery_persists_bounded_state_graph(tmp_path: Path, site_url: str) -> None:
    config = ProjectConfig(
        name="discovery test",
        base_url=site_url,
        allowed_origins={site_url},
        roles=[RoleConfig(name="admin")],
    )
    database = tmp_path / ".web2doc/state.sqlite3"
    upgrade_database(database)
    repository = Repository(database)
    project_id, roles = repository.register_project(tmp_path, config)
    browser = PlaywrightBrowser(project_root=tmp_path, config=config, role=config.role("admin"))
    runner = ExplorationRunner(
        repository=repository,
        artifacts=ArtifactStore(tmp_path / ".web2doc"),
        browser=browser,
        policy=ActionPolicy(config),
        planner=HeuristicPlanner(),
        config=config,
        project_id=project_id,
        role_id=roles["admin"],
        role_name="admin",
    )
    try:
        run_id = await runner.run(
            mode=DiscoveryMode.UNGUIDED,
            limits=DiscoveryLimits(max_actions=2),
        )
        report = repository.discovery_report(run_id)
        assert report["run"]["stop_reason"] == "action_budget_exhausted"
        assert report["coverage"]["states"] == 2
        assert report["coverage"]["transitions"] == 1
        assert "View details" in {feature["title"] for feature in report["features"]}
        assert any(item["status"] == "skipped" for item in report["unexplored"])
    finally:
        repository.close()
