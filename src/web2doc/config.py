from __future__ import annotations

import json
import tomllib
from pathlib import Path
from urllib.parse import urlsplit

from pydantic import TypeAdapter

from web2doc.domain.models import Procedure, ProjectConfig

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


def initialize_project(project_dir: Path, name: str, base_url: str) -> Path:
    project_dir.mkdir(parents=True, exist_ok=True)
    project_file = project_dir / PROJECT_FILE
    if project_file.exists():
        raise FileExistsError(f"project already exists: {project_file}")
    origin = origin_for(base_url)
    quoted = {
        key: json.dumps(value)
        for key, value in {"name": name, "url": base_url, "origin": origin}.items()
    }
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
                "allowed_write_operations = []",
                "supporting_origins = []",
                "",
            ]
        ),
        encoding="utf-8",
    )
    runtime = project_dir / RUNTIME_DIR
    for child in ("artifacts", "private/auth", "private/traces"):
        (runtime / child).mkdir(parents=True, exist_ok=True)
    return project_file
