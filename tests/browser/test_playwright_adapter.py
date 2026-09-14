from __future__ import annotations

import socket
import threading
import time
from pathlib import Path

import httpx
import pytest
import uvicorn

from tests.fixtures.site_app import app
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
