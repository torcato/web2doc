from __future__ import annotations

from pathlib import Path

import pytest

from web2doc.domain.models import PolicyConfig, ProjectConfig, RoleConfig
from web2doc.storage.database import upgrade_database
from web2doc.storage.repository import Repository


@pytest.fixture
def project_config() -> ProjectConfig:
    return ProjectConfig(
        name="test project",
        base_url="http://127.0.0.1:8765",
        allowed_origins={"http://127.0.0.1:8765"},
        roles=[RoleConfig(name="admin", storage_state=".web2doc/private/auth/admin.json")],
        policy=PolicyConfig(
            allowed_write_operations={"create-item"},
            supporting_origins=set(),
        ),
    )


@pytest.fixture
def repository(tmp_path: Path, project_config: ProjectConfig) -> Repository:
    database = tmp_path / ".web2doc" / "state.sqlite3"
    upgrade_database(database)
    value = Repository(database)
    value.register_project(tmp_path, project_config)
    try:
        yield value
    finally:
        value.close()
