from __future__ import annotations

import json
import tomllib
from pathlib import Path
from urllib.parse import urlsplit

from pydantic import TypeAdapter

from web2doc.documentation.models import DocumentContent
from web2doc.domain.models import Procedure, ProjectConfig
from web2doc.verification.models import WorkflowDefinition

PROJECT_FILE = "project.toml"
RUNTIME_DIR = ".web2doc"


def origin_for(url: str) -> str:
    parsed = urlsplit(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError(f"invalid HTTP(S) URL: {url}")
    default = (parsed.scheme == "http" and parsed.port in {None, 80}) or (
        parsed.scheme == "https" and parsed.port in {None, 443}
    )
    port = "" if default else f":{parsed.port}"
    return f"{parsed.scheme}://{parsed.hostname.lower()}{port}"


def load_project(project_dir: Path) -> ProjectConfig:
    with (project_dir / PROJECT_FILE).open("rb") as stream:
        return ProjectConfig.model_validate(tomllib.load(stream))


def load_procedure(path: Path) -> Procedure:
    return TypeAdapter(Procedure).validate_json(path.read_bytes())


def load_workflow(path: Path) -> WorkflowDefinition:
    return TypeAdapter(WorkflowDefinition).validate_json(path.read_bytes())


def load_document_content(path: Path) -> DocumentContent:
    return TypeAdapter(DocumentContent).validate_json(path.read_bytes())


def initialize_project(project_dir: Path, name: str, base_url: str) -> Path:
    project_dir.mkdir(parents=True, exist_ok=True)
    project_file = project_dir / PROJECT_FILE
    if project_file.exists():
        raise FileExistsError(f"project already exists: {project_file}")
    origin = origin_for(base_url)
    quoted = {key: json.dumps(value) for key, value in {"name": name, "url": base_url, "origin": origin}.items()}
    project_file.write_text(
        "\n".join(
            [
                f"name = {quoted['name']}",
                f"base_url = {quoted['url']}",
                f"allowed_origins = [{quoted['origin']}]",
                "",
                "[[roles]]",
                'name = "default"',
                'storage_state = ".web2doc/private/auth/default.json"',
                "",
                "[policy]",
                'allowed_actions = ["navigate", "click", "fill", "select", "press", "scroll", "wait"]',
                'allowed_write_operations = ["click-confirm"]',
                "supporting_origins = []",
                "",
                "[discovery]",
                'scenario = "default"',
                'ignored_query_parameters = ["_", "cache_bust", "cacheBust", "nonce", "timestamp", "ts"]',
                "volatile_patterns = [",
                "  '\\b\\d{4}-\\d{2}-\\d{2}[T ][0-9:.+Z-]+\\b',",
                "  '\\b[0-9a-fA-F]{8}-[0-9a-fA-F-]{27,}\\b',",
                "]",
                "",
                "[discovery.limits]",
                "max_actions = 200",
                "max_states = 100",
                "max_depth = 12",
                "max_duration_seconds = 1800",
                "max_model_calls = 100",
                "max_output_tokens = 100000",
                "max_tokens_per_call = 2000",
                "max_candidates_per_state = 20",
                "max_visits_per_state = 3",
                "model_retries = 2",
                "",
            ]
        ),
        encoding="utf-8",
    )
    runtime = project_dir / RUNTIME_DIR
    for child in ("artifacts", "private/auth", "private/traces"):
        (runtime / child).mkdir(parents=True, exist_ok=True)
    return project_file
