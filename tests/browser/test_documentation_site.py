from __future__ import annotations

from pathlib import Path

import pytest
from playwright.async_api import async_playwright

from tests.integration.test_documentation import publisher, verified_workflow
from web2doc.documentation.composer import DeterministicComposer
from web2doc.documentation.models import ReviewDecision
from web2doc.documentation.service import DocumentationService
from web2doc.domain.models import ProjectConfig
from web2doc.storage.repository import Repository


@pytest.mark.browser
@pytest.mark.asyncio
async def test_exported_site_renders_at_desktop_and_narrow_widths(
    repository: Repository,
    tmp_path: Path,
    project_config: ProjectConfig,
) -> None:
    project_id, _verification_id, workflow = await verified_workflow(
        repository, tmp_path, project_config, key="rendered-guide"
    )
    document = await DocumentationService(repository, project_id).generate(workflow.id, DeterministicComposer())
    repository.add_review_decision(document.id, ReviewDecision.APPROVED, "Owner", "Visual QA")
    export = publisher(repository, tmp_path, project_id).export_approved(tmp_path / "render-export")
    guide_url = (export / "site" / "guides" / "rendered-guide" / "index.html").as_uri()

    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch()
        try:
            page = await browser.new_page()
            for width in (1440, 390):
                await page.set_viewport_size({"width": width, "height": 900})
                await page.goto(guide_url, wait_until="load")
                assert await page.locator("h1").inner_text() == "Use <unsafe> [feature](javascript:alert(1))"
                assert await page.locator("img").count() >= 2
                assert await page.evaluate(
                    "document.documentElement.scrollWidth <= document.documentElement.clientWidth"
                )
                assert (await page.screenshot()).startswith(b"\x89PNG")
        finally:
            await browser.close()
