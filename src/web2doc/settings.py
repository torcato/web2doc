from __future__ import annotations

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class RuntimeSettings(BaseSettings):
    """Process-level settings; project scope and permissions stay in project.toml."""

    model_config = SettingsConfigDict(env_prefix="WEB2DOC_", extra="ignore")

    browser_channel: str | None = None
    browser_executable_path: Path | None = None
    browser_slow_mo_ms: int = Field(default=0, ge=0, le=10_000)
    llm_model: str | None = None
