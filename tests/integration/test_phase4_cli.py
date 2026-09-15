from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from web2doc.cli import app


def test_phase_four_commands_initialize_sources_and_coverage(tmp_path: Path) -> None:
    runner = CliRunner()
    project = tmp_path / "project"
    result = runner.invoke(
        app,
        ["init", "docs-test", "--base-url", "http://127.0.0.1:8765", "--path", str(project)],
    )
    assert result.exit_code == 0, result.output

    source = tmp_path / "terminology.txt"
    source.write_text("Use record instead of item.", encoding="utf-8")
    result = runner.invoke(
        app,
        [
            "owner-source-add",
            str(project),
            str(source),
            "--kind",
            "terminology",
            "--label",
            "Vocabulary",
        ],
    )
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["kind"] == "terminology"

    result = runner.invoke(app, ["documentation-coverage", str(project)])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["report"]["summary"]["workflows"] == 0
    assert Path(payload["json_path"]).is_file()
    assert Path(payload["markdown_path"]).is_file()

    help_result = runner.invoke(app, ["--help"])
    assert help_result.exit_code == 0
    for command in (
        "document-generate",
        "document-revise",
        "document-review",
        "document-bundle",
        "documentation-coverage",
        "docs-export",
    ):
        assert command in help_result.output
