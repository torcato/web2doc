from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from playwright.async_api import (
    Browser,
    BrowserContext,
    Locator,
    Page,
    Playwright,
    Route,
    async_playwright,
)

from web2doc.domain.models import (
    Action,
    ClickAction,
    ExecutionResult,
    FillAction,
    NavigateAction,
    ObservationDraft,
    PressAction,
    ProjectConfig,
    RoleConfig,
    ScrollAction,
    SelectAction,
    Target,
    WaitAction,
)
from web2doc.policy.actions import ActionPolicy


class BrowserExecutionError(RuntimeError):
    pass


class TargetNotFoundError(BrowserExecutionError):
    pass


class AmbiguousTargetError(BrowserExecutionError):
    pass


class ScopeViolationError(BrowserExecutionError):
    pass


@dataclass
class PlaywrightSession:
    playwright: Playwright
    browser: Browser
    context: BrowserContext
    page: Page
    trace_path: Path


class PlaywrightBrowser:
    def __init__(
        self,
        *,
        project_root: Path,
        config: ProjectConfig,
        role: RoleConfig,
    ) -> None:
        self.project_root = project_root.resolve()
        self.config = config
        self.role = role
        self.policy = ActionPolicy(config)

    async def start(self, *, run_id: str, headed: bool = False) -> PlaywrightSession:
        playwright = await async_playwright().start()
        browser: Browser | None = None
        try:
            browser = await playwright.chromium.launch(headless=not headed)
            context_options: dict[str, Any] = {
                "viewport": {"width": 1440, "height": 1000},
                "locale": "en-US",
                "timezone_id": "UTC",
            }
            if self.role.storage_state:
                storage_path = (self.project_root / self.role.storage_state).resolve()
                if not storage_path.is_relative_to(self.project_root):
                    raise ScopeViolationError("authentication state path escapes the project")
                if storage_path.exists():
                    context_options["storage_state"] = str(storage_path)
            context = await browser.new_context(**context_options)
            await context.route("**/*", self._route_request)
            page = await context.new_page()
            trace_path = self.project_root / ".web2doc" / "private" / "traces" / f"{run_id}.zip"
            trace_path.parent.mkdir(parents=True, exist_ok=True)
            await context.tracing.start(screenshots=True, snapshots=True, sources=False)
            return PlaywrightSession(playwright, browser, context, page, trace_path)
        except BaseException:
            if browser is not None:
                await browser.close()
            await playwright.stop()
            raise

    async def _route_request(self, route: Route) -> None:
        request = route.request
        allowed = (
            self.policy.navigation_allowed(request.url)
            if request.is_navigation_request()
            else self.policy.resource_allowed(request.url)
        )
        if allowed:
            await route.continue_()
        else:
            await route.abort("blockedbyclient")

    async def observe(self, session: PlaywrightSession) -> ObservationDraft:
        await self._check_open_pages(session)
        body = session.page.locator("body")
        try:
            aria = await body.aria_snapshot(mode="ai", timeout=10_000)
        except TypeError:  # pragma: no cover - compatibility with earlier supported Playwright
            aria = await body.aria_snapshot(timeout=10_000)
        screenshot = await session.page.screenshot(full_page=True, type="png")
        return ObservationDraft(
            url=session.page.url,
            title=await session.page.title(),
            aria_snapshot=aria,
            screenshot=screenshot,
        )

    async def execute(self, session: PlaywrightSession, action: Action) -> ExecutionResult:
        timeout = action.timeout_ms
        if isinstance(action, NavigateAction):
            await session.page.goto(action.url, wait_until="domcontentloaded", timeout=timeout)
        elif isinstance(action, ClickAction):
            await (await self._resolve_target(session.page, action.target)).click(timeout=timeout)
        elif isinstance(action, FillAction):
            await (await self._resolve_target(session.page, action.target)).fill(
                action.value, timeout=timeout
            )
        elif isinstance(action, SelectAction):
            await (await self._resolve_target(session.page, action.target)).select_option(
                action.value, timeout=timeout
            )
        elif isinstance(action, PressAction):
            if action.target is None:
                await session.page.keyboard.press(action.key)
            else:
                await (await self._resolve_target(session.page, action.target)).press(
                    action.key, timeout=timeout
                )
        elif isinstance(action, ScrollAction):
            await session.page.mouse.wheel(0, action.delta_y)
        elif isinstance(action, WaitAction):
            await session.page.get_by_text(action.text, exact=False).first.wait_for(
                state="visible", timeout=timeout
            )
        else:  # pragma: no cover - closed union protects this branch
            raise BrowserExecutionError(f"unsupported action: {type(action).__name__}")
        await self._check_open_pages(session)
        return ExecutionResult(final_url=session.page.url, message=f"completed {action.kind}")

    async def _resolve_target(self, page: Page, target: Target) -> Locator:
        scope: Page | Any = page
        if target.frame_url:
            matches = [frame for frame in page.frames if target.frame_url in frame.url]
            if len(matches) != 1:
                if not matches:
                    raise TargetNotFoundError(f"frame not found: {target.frame_url}")
                raise AmbiguousTargetError(f"multiple frames match: {target.frame_url}")
            scope = matches[0]

        if target.test_id:
            locator = scope.get_by_test_id(target.test_id)
        elif target.label:
            locator = scope.get_by_label(target.label, exact=target.exact)
        elif target.role and target.name:
            locator = scope.get_by_role(
                target.role,  # type: ignore[arg-type]
                name=target.name,
                exact=target.exact,
            )
        elif target.css:
            locator = scope.locator(target.css)
        else:  # pragma: no cover - Target validation protects this branch
            raise TargetNotFoundError("target has no usable selector")

        count = await locator.count()
        if count == 0:
            raise TargetNotFoundError(f"target not found: {target.model_dump(exclude_none=True)}")
        if count > 1:
            raise AmbiguousTargetError(
                f"target matched {count} elements: {target.model_dump(exclude_none=True)}"
            )
        return locator

    async def _check_open_pages(self, session: PlaywrightSession) -> None:
        pages = [page for page in session.context.pages if not page.is_closed()]
        for page in pages:
            if page.url != "about:blank" and not self.policy.navigation_allowed(page.url):
                await page.close()
                raise ScopeViolationError(f"page navigated outside allowed origins: {page.url}")
        if not pages:
            raise BrowserExecutionError("browser context has no open pages")
        session.page = pages[-1]

    async def save_authentication(self, session: PlaywrightSession) -> Path:
        if not self.role.storage_state:
            raise ValueError(f"role {self.role.name!r} has no storage_state configured")
        path = (self.project_root / self.role.storage_state).resolve()
        if not path.is_relative_to(self.project_root):
            raise ScopeViolationError("authentication state path escapes the project")
        path.parent.mkdir(parents=True, exist_ok=True)
        await session.context.storage_state(path=str(path))
        return path

    async def close(self, session: PlaywrightSession) -> None:
        try:
            try:
                await session.context.tracing.stop(path=session.trace_path)
            finally:
                await session.context.close()
        finally:
            try:
                await session.browser.close()
            finally:
                await session.playwright.stop()
