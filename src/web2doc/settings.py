from __future__ import annotations

import os
from pathlib import Path

from dotenv import dotenv_values
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

PROVIDER_ENVIRONMENT_KEYS = {
    "GOOGLE_APPLICATION_CREDENTIALS",
    "GOOGLE_API_KEY",
    "GOOGLE_CLOUD_LOCATION",
    "GOOGLE_CLOUD_PROJECT",
    "OPENAI_API_KEY",
    "OPENAI_BASE_URL",
}


class RuntimeSettings(BaseSettings):
    """Process-level settings; project scope and permissions stay in project.toml."""

    model_config = SettingsConfigDict(env_prefix="WEB2DOC_", extra="ignore")

    browser_channel: str | None = None
    browser_executable_path: Path | None = None
    browser_slow_mo_ms: int = Field(default=0, ge=0, le=10_000)
    llm_model: str | None = None
    discovery_model: str | None = None
    documentation_model: str | None = None

    def model_for_discovery(self, override: str | None = None) -> str | None:
        return override or self.discovery_model or self.llm_model

    def model_for_documentation(self, override: str | None = None) -> str | None:
        return override or self.documentation_model or self.llm_model


def load_runtime_settings(project_dir: Path) -> RuntimeSettings:
    """Load recognized settings from the process, working tree, and project dotenv files.

    Real process environment variables have highest precedence. A project-local
    ``.env`` overrides the current working directory's ``.env`` when they differ.
    Values are placed in the process environment because provider SDKs resolve
    their own credentials there.
    """

    project_root = project_dir.resolve()
    working_tree = Path.cwd().resolve()
    candidates: list[Path] = []
    if project_root == working_tree or project_root.is_relative_to(working_tree):
        candidates.append(working_tree / ".env")
    candidates.append(project_root / ".env")
    merged: dict[str, str] = {}
    seen: set[Path] = set()
    for path in candidates:
        if path in seen or not path.is_file():
            continue
        seen.add(path)
        for key, value in dotenv_values(path).items():
            if value is None or not (key.startswith("WEB2DOC_") or key in PROVIDER_ENVIRONMENT_KEYS):
                continue
            merged[key] = value
    for key, value in merged.items():
        os.environ.setdefault(key, value)
    return RuntimeSettings()
