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
    Request,
    Route,
    async_playwright,
)
from playwright.async_api import (
    TimeoutError as PlaywrightTimeoutError,
)
from pydantic import TypeAdapter

from web2doc.browser.base import (
    AmbiguousTargetError,
    BrowserExecutionError,
    ScopeViolationError,
    TargetNotFoundError,
)
from web2doc.domain.models import (
    Action,
    ClickAction,
    ControlDraft,
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
from web2doc.settings import RuntimeSettings


@dataclass
class PlaywrightSession:
    playwright: Playwright
    browser: Browser
    context: BrowserContext
    page: Page
    trace_path: Path
    blocked_requests: list[str]


class PlaywrightBrowser:
    def __init__(
        self,
        *,
        project_root: Path,
        config: ProjectConfig,
        role: RoleConfig,
        settings: RuntimeSettings | None = None,
    ) -> None:
        self.project_root = project_root.resolve()
        self.config = config
        self.role = role
        self.policy = ActionPolicy(config)
        self.settings = settings or RuntimeSettings()

    async def start(self, *, run_id: str, headed: bool = False) -> PlaywrightSession:
        playwright = await async_playwright().start()
        browser: Browser | None = None
        try:
            launch_options: dict[str, Any] = {
                "headless": not headed,
                "slow_mo": self.settings.browser_slow_mo_ms,
            }
            if self.settings.browser_channel:
                launch_options["channel"] = self.settings.browser_channel
            if self.settings.browser_executable_path:
                launch_options["executable_path"] = str(self.settings.browser_executable_path)
            browser = await playwright.chromium.launch(**launch_options)
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
            blocked_requests: list[str] = []

            def record_disallowed_request(request: Request) -> None:
                if not self._request_allowed(request) and request.url not in blocked_requests:
                    blocked_requests.append(request.url)

            async def guard_request(route: Route) -> None:
                await self._route_request(route, blocked_requests)

            context.on("request", record_disallowed_request)
            await context.route("**/*", guard_request)
            page = await context.new_page()
            trace_path = self.project_root / ".web2doc" / "private" / "traces" / f"{run_id}.zip"
            trace_path.parent.mkdir(parents=True, exist_ok=True)
            await context.tracing.start(screenshots=True, snapshots=True, sources=False)
            return PlaywrightSession(playwright, browser, context, page, trace_path, blocked_requests)
        except BaseException:
            if browser is not None:
                await browser.close()
            await playwright.stop()
            raise

    async def _route_request(self, route: Route, blocked_requests: list[str]) -> None:
        request = route.request
        if self._request_allowed(request):
            await route.continue_()
        else:
            if request.url not in blocked_requests:
                blocked_requests.append(request.url)
            await route.abort("blockedbyclient")

    def _request_allowed(self, request: Request) -> bool:
        return (
            self.policy.navigation_allowed(request.url)
            if request.is_navigation_request()
            else self.policy.resource_allowed(request.url)
        )

    async def observe(self, session: PlaywrightSession) -> ObservationDraft:
        await self._check_open_pages(session)
        await self._inject_synthetic_labels(session.page)
        
        body = session.page.locator("body")
        try:
            aria = await body.aria_snapshot(mode="ai", timeout=10_000)
        except TypeError:  # pragma: no cover - compatibility with earlier supported Playwright
            aria = await body.aria_snapshot(timeout=10_000)
        screenshot = await session.page.screenshot(full_page=True, type="png")
        controls = TypeAdapter(list[ControlDraft]).validate_python(
            await session.page.locator("a[href], button, input, select, textarea, [role]").evaluate_all(
                """
                elements => elements.filter(element => {
                  const style = getComputedStyle(element);
                  const rect = element.getBoundingClientRect();
                  return style.visibility !== "hidden" && style.display !== "none" && rect.width > 0 && rect.height > 0;
                }).map(element => {
                  const tag = element.tagName.toLowerCase();
                  const inputType = tag === "input" ? (element.getAttribute("type") || "text").toLowerCase() : null;
                  let role = element.getAttribute("role");
                  if (!role) {
                    if (tag === "a") role = "link";
                    else if (tag === "button" || inputType === "submit" || inputType === "button") role = "button";
                    else if (tag === "select") role = "combobox";
                    else if (
                      tag === "textarea" ||
                      ["text", "email", "search", "url", "tel", "number"].includes(inputType)
                    ) role = "textbox";
                    else if (inputType === "checkbox") role = "checkbox";
                    else if (inputType === "radio") role = "radio";
                    else role = tag;
                  }
                  const id = element.getAttribute("id");
                  const label = id
                    ? document.querySelector(`label[for="${CSS.escape(id)}"]`)?.textContent?.trim()
                    : null;
                  const labelledBy = (element.getAttribute("aria-labelledby") || "")
                    .split(/\\s+/)
                    .filter(Boolean)
                    .map(reference => document.getElementById(reference)?.textContent?.trim())
                    .filter(Boolean)
                    .join(" ");
                  const valueName = ["button", "submit", "reset"].includes(inputType)
                    ? element.getAttribute("value")
                    : null;
                  const descendantName = element.querySelector("img[alt]")?.getAttribute("alt") ||
                    element.querySelector("svg title")?.textContent?.trim();
                  const name = labelledBy || element.getAttribute("aria-label") || label ||
                    element.textContent?.trim() || valueName || descendantName ||
                    element.getAttribute("title") || element.getAttribute("placeholder") || "";
                  return {
                    role,
                    name: name.slice(0, 300),
                    href: tag === "a" ? element.href : null,
                    label,
                    test_id: element.getAttribute("data-testid"),
                    input_type: inputType,
                    disabled: Boolean(element.disabled || element.getAttribute("aria-disabled") === "true"),
                    options: tag === "select"
                      ? Array.from(element.options).map(option => option.value).filter(Boolean).slice(0, 20)
                      : [],
                  };
                })
                """
            )
        )
        return ObservationDraft(
            url=session.page.url,
            title=await session.page.title(),
            aria_snapshot=aria,
            screenshot=screenshot,
            controls=controls,
            active_dialogs=await self._visible_texts(session.page, '[role="dialog"], dialog[open]'),
            selected_tabs=await self._visible_texts(session.page, '[role="tab"][aria-selected="true"]'),
            alerts=await self._visible_texts(session.page, '[role="alert"], [aria-live="assertive"]'),
            invalid_controls=await self._visible_texts(session.page, '[aria-invalid="true"], :user-invalid'),
        )

    async def _visible_texts(self, page: Page, selector: str) -> list[str]:
        values: object = await page.locator(selector).evaluate_all(
            """
            elements => elements.filter(element => {
              const style = getComputedStyle(element);
              const rect = element.getBoundingClientRect();
              return style.visibility !== "hidden" && style.display !== "none" && rect.width > 0 && rect.height > 0;
            }).map(element => (
              element.getAttribute("aria-label") ||
              element.textContent?.trim() ||
              element.getAttribute("name") ||
              "unnamed"
            ).slice(0, 500))
            """
        )
        return TypeAdapter(list[str]).validate_python(values)

    async def _inject_synthetic_labels(self, page: Page) -> None:
        await page.evaluate("""
            document.querySelectorAll('button, a, [role="button"], [role="link"]').forEach((el, index) => {
                const hasLabel = el.getAttribute('aria-label') || el.getAttribute('aria-labelledby');
                const hasTitle = el.getAttribute('title');
                const hasText = el.innerText && el.innerText.trim().length > 0;
                
                if (!hasLabel && !hasTitle && !hasText) {
                    const svg = el.querySelector('svg');
                    let hint = 'element';
                    if (svg) {
                        const svgClass = typeof svg.className === 'string' ? svg.className : (svg.className && svg.className.baseVal ? svg.className.baseVal : '');
                        hint = svgClass.replace(/[^a-zA-Z0-9-]/g, ' ').trim() || 'icon';
                    }
                    el.setAttribute('aria-label', `Unnamed ${hint} ${index}`);
                    el.setAttribute('data-web2doc-synthetic', 'true');
                }
            });
        """)

    async def execute(self, session: PlaywrightSession, action: Action) -> ExecutionResult:
        timeout = action.timeout_ms
        session.blocked_requests.clear()
        await self._inject_synthetic_labels(session.page)
        try:
            if isinstance(action, NavigateAction):
                await session.page.goto(action.url, wait_until="domcontentloaded", timeout=timeout)
            elif isinstance(action, ClickAction):
                target = await self._resolve_target(session.page, action.target, timeout)
                await target.click(timeout=timeout)
            elif isinstance(action, FillAction):
                target = await self._resolve_target(session.page, action.target, timeout)
                await target.fill(action.value, timeout=timeout)
            elif isinstance(action, SelectAction):
                target = await self._resolve_target(session.page, action.target, timeout)
                await target.select_option(action.value, timeout=timeout)
            elif isinstance(action, PressAction):
                if action.target is None:
                    await session.page.keyboard.press(action.key)
                else:
                    target = await self._resolve_target(session.page, action.target, timeout)
                    await target.press(action.key, timeout=timeout)
            elif isinstance(action, ScrollAction):
                await session.page.mouse.wheel(0, action.delta_y)
            elif isinstance(action, WaitAction):
                target = session.page.get_by_text(action.text, exact=False).first
                await target.wait_for(state="visible", timeout=timeout)
            else:  # pragma: no cover - closed union protects this branch
                raise BrowserExecutionError(f"unsupported action: {type(action).__name__}")
        except BaseException as exc:
            self._raise_if_request_was_blocked(session, cause=exc)
            raise
        self._raise_if_request_was_blocked(session)
        await self._check_open_pages(session)
        return ExecutionResult(final_url=session.page.url, message=f"completed {action.kind}")

    def _raise_if_request_was_blocked(
        self,
        session: PlaywrightSession,
        *,
        cause: BaseException | None = None,
    ) -> None:
        if not session.blocked_requests:
            return
        blocked = ", ".join(session.blocked_requests[:3])
        error = ScopeViolationError(f"browser request blocked by origin policy: {blocked}")
        if cause is not None:
            raise error from cause
        raise error

    async def _resolve_target(self, page: Page, target: Target, timeout: float) -> Locator:
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

        try:
            await locator.first.wait_for(state="attached", timeout=timeout)
        except PlaywrightTimeoutError as exc:
            raise TargetNotFoundError(f"target not found: {target.model_dump(exclude_none=True)}") from exc
        count = await locator.count()
        if count == 0:
            raise TargetNotFoundError(f"target not found: {target.model_dump(exclude_none=True)}")
        if count > 1:
            raise AmbiguousTargetError(f"target matched {count} elements: {target.model_dump(exclude_none=True)}")
        return locator

    async def _check_open_pages(self, session: PlaywrightSession) -> None:
        pages = [page for page in session.context.pages if not page.is_closed()]
        for page in pages:
            if page.url != "about:blank" and not self.policy.navigation_allowed(page.url):
                await page.close()
                raise ScopeViolationError(f"page navigated outside allowed origins: {page.url}")
        if not pages:
            raise BrowserExecutionError("browser context has no open pages")
        nonblank_pages = [page for page in pages if page.url != "about:blank"]
        session.page = nonblank_pages[-1] if nonblank_pages else pages[-1]

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
