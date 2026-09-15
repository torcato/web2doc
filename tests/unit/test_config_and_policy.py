from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from pydantic import ValidationError

from web2doc.config import initialize_project, load_project, origin_for
from web2doc.domain.models import ClickAction, Effect, NavigateAction, Target
from web2doc.policy.actions import ActionPolicy
from web2doc.settings import RuntimeSettings, load_runtime_settings


def test_initialize_and_load_project(tmp_path: Path) -> None:
    project_file = initialize_project(tmp_path / "demo", "Demo", "https://Example.com/path")

    config = load_project(project_file.parent)

    assert config.name == "Demo"
    assert config.allowed_origins == {"https://example.com"}
    assert config.roles[0].name == "default"
    assert config.policy.allowed_write_operations == {"click-confirm"}
    assert (project_file.parent / ".web2doc/private/auth").is_dir()


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://Example.com/path", "https://example.com"),
        ("http://example.com:80/a", "http://example.com"),
        ("https://example.com:8443/a", "https://example.com:8443"),
    ],
)
def test_origin_for_normalizes_urls(url: str, expected: str) -> None:
    assert origin_for(url) == expected


def test_target_requires_a_semantic_selector() -> None:
    with pytest.raises(ValidationError):
        Target()


def test_write_action_requires_operation_identifier() -> None:
    with pytest.raises(ValidationError):
        ClickAction(
            description="Create",
            effect=Effect.WRITE,
            target=Target(role="button", name="Create"),
        )


def test_policy_rejects_external_navigation(project_config) -> None:
    decision = ActionPolicy(project_config).evaluate(
        NavigateAction(description="Leave", url="https://outside.example/")
    )

    assert not decision.allowed
    assert "origin" in decision.reason


def test_policy_requires_named_write_permission(project_config) -> None:
    denied = ClickAction(
        description="Delete",
        effect=Effect.WRITE,
        operation_id="delete-item",
        target=Target(role="button", name="Delete"),
    )
    allowed = ClickAction(
        description="Create",
        effect=Effect.WRITE,
        operation_id="create-item",
        target=Target(role="button", name="Create"),
    )

    policy = ActionPolicy(project_config)
    assert not policy.evaluate(denied).allowed
    assert policy.evaluate(allowed).allowed


def test_generated_toml_quotes_untrusted_values(tmp_path: Path) -> None:
    path = initialize_project(tmp_path / "quoted", 'name"\nvalue', "http://localhost:9999/")

    raw = path.read_text(encoding="utf-8")
    assert json.dumps('name"\nvalue') in raw
    assert load_project(path.parent).name == 'name"\nvalue'


def test_runtime_settings_use_namespaced_environment(monkeypatch) -> None:
    monkeypatch.setenv("WEB2DOC_BROWSER_CHANNEL", "chrome")
    monkeypatch.setenv("WEB2DOC_BROWSER_SLOW_MO_MS", "25")

    settings = RuntimeSettings()

    assert settings.browser_channel == "chrome"
    assert settings.browser_slow_mo_ms == 25


def test_runtime_settings_select_purpose_specific_models(monkeypatch) -> None:
    monkeypatch.setenv("WEB2DOC_LLM_MODEL", "openai:fallback")
    monkeypatch.setenv("WEB2DOC_DISCOVERY_MODEL", "google-cloud:discovery")
    monkeypatch.setenv("WEB2DOC_DOCUMENTATION_MODEL", "google-cloud:documentation")

    settings = RuntimeSettings()

    assert settings.model_for_discovery() == "google-cloud:discovery"
    assert settings.model_for_documentation() == "google-cloud:documentation"
    assert settings.model_for_discovery("openai:override") == "openai:override"


def test_project_dotenv_overrides_working_tree_dotenv_but_not_process_environment(
    tmp_path: Path, monkeypatch
) -> None:
    working_tree = tmp_path / "working-tree"
    project = working_tree / "project"
    project.mkdir(parents=True)
    (working_tree / ".env").write_text(
        "WEB2DOC_DISCOVERY_MODEL=openai:working-tree\nUNRELATED_SECRET=not-loaded\n",
        encoding="utf-8",
    )
    (project / ".env").write_text(
        "WEB2DOC_DISCOVERY_MODEL=google-cloud:project\n"
        "WEB2DOC_DOCUMENTATION_MODEL=google-cloud:documentation\n"
        "GOOGLE_CLOUD_PROJECT=dotenv-project\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(working_tree)
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "process-project")
    monkeypatch.delenv("WEB2DOC_DISCOVERY_MODEL", raising=False)
    monkeypatch.delenv("WEB2DOC_DOCUMENTATION_MODEL", raising=False)
    monkeypatch.delenv("UNRELATED_SECRET", raising=False)

    settings = load_runtime_settings(project)

    assert settings.discovery_model == "google-cloud:project"
    assert settings.documentation_model == "google-cloud:documentation"
    assert os.environ["GOOGLE_CLOUD_PROJECT"] == "process-project"
    assert "UNRELATED_SECRET" not in os.environ
