from __future__ import annotations

import socket
import threading
import time
from pathlib import Path

import httpx
import pytest
import uvicorn

from tests.fixtures.site_app import app
from web2doc.browser.playwright import AmbiguousTargetError, PlaywrightBrowser
from web2doc.domain.models import (
    ClickAction,
    FillAction,
    NavigateAction,
    PolicyConfig,
    ProjectConfig,
    RoleConfig,
    Target,
)


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
        assert (await httpx.AsyncClient().get(f"{site_url}/__state")).json() == {
            "items": ["Evidence item"]
        }
    finally:
        await browser.close(session)


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
