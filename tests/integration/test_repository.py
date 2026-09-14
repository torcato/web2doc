from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from sqlalchemy.exc import IntegrityError

from web2doc.domain.models import ClickAction, Effect, RunStatus, Target
from web2doc.storage.database import upgrade_database
from web2doc.storage.repository import ProjectBusyError


def test_migration_creates_expected_schema(tmp_path: Path) -> None:
    database = tmp_path / "state.sqlite3"
    upgrade_database(database)

    with sqlite3.connect(database) as connection:
        tables = {
            row[0]
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        }

    assert {
        "projects",
        "roles",
        "runs",
        "artifacts",
        "observations",
        "action_attempts",
        "project_locks",
        "alembic_version",
    } <= tables


def test_project_lock_prevents_concurrent_runner(repository, tmp_path, project_config) -> None:
    project_id, roles = repository.register_project(tmp_path, project_config)
    first = repository.create_run(project_id, roles["admin"], "first")
    second = repository.create_run(project_id, roles["admin"], "second")
    repository.acquire_project_lock(project_id, first.id)

    with pytest.raises(ProjectBusyError):
        repository.acquire_project_lock(project_id, second.id)

    repository.release_project_lock(project_id, first.id)
    repository.acquire_project_lock(project_id, second.id)


def test_recovery_marks_executing_attempt_uncertain(repository, tmp_path, project_config) -> None:
    project_id, roles = repository.register_project(tmp_path, project_config)
    run = repository.create_run(project_id, roles["admin"], "create")
    repository.set_run_status(run.id, RunStatus.RUNNING)
    repository.acquire_project_lock(project_id, run.id)
    action = ClickAction(
        description="Create item",
        effect=Effect.WRITE,
        operation_id="create-item",
        target=Target(role="button", name="Create"),
    )

    # Seed a minimum observation and executing attempt through valid foreign keys.
    from web2doc.domain.models import ObservationDraft, Sensitivity
    from web2doc.storage.artifacts import ArtifactStore

    store = ArtifactStore(tmp_path / ".web2doc")
    aria = store.write(
        run_id=run.id,
        category="observations",
        content=b"body",
        suffix=".yaml",
        media_type="application/yaml",
        sensitivity=Sensitivity.PRIVATE,
    )
    screenshot = store.write(
        run_id=run.id,
        category="screenshots",
        content=b"png",
        suffix=".png",
        media_type="image/png",
        sensitivity=Sensitivity.PRIVATE,
    )
    repository.add_artifact(run.id, aria)
    repository.add_artifact(run.id, screenshot)
    observation = repository.add_observation(
        run.id,
        ObservationDraft(
            url="http://127.0.0.1:8765", title="Test", aria_snapshot="body", screenshot=b"png"
        ),
        aria.id,
        screenshot.id,
    )
    attempt = repository.create_attempt(run.id, 1, action, observation.id)
    from web2doc.domain.models import AttemptStatus

    repository.set_attempt_status(attempt.id, AttemptStatus.EXECUTING)

    result = repository.recover_interrupted(project_id)

    assert result == {"attempts_marked_uncertain": 1, "runs_paused": 1}
    assert repository.list_attempts(run.id)[0].status == "uncertain"
    assert repository.get_run(run.id).status == "paused"


def test_foreign_keys_are_enforced(repository) -> None:
    from web2doc.domain.models import ArtifactDraft, Sensitivity

    with pytest.raises(IntegrityError):
        repository.add_artifact(
            "missing-run",
            ArtifactDraft(
                relative_path="artifacts/missing/file.txt",
                sha256="0" * 64,
                media_type="text/plain",
                sensitivity=Sensitivity.PRIVATE,
                size_bytes=0,
            ),
        )
