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
        tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}

    assert {
        "projects",
        "roles",
        "runs",
        "artifacts",
        "observations",
        "action_attempts",
        "project_locks",
        "alembic_version",
        "states",
        "transitions",
        "frontier_items",
        "features",
        "usage_events",
        "workflows",
        "workflow_revisions",
        "workflow_steps",
        "fixture_receipts",
        "verifications",
        "predicate_results",
        "owner_sources",
        "document_revisions",
        "document_evidence",
        "review_decisions",
        "exports",
        "capture_manifests",
        "processing_attempts",
        "distilled_features",
        "feature_reference_revisions",
        "feature_reference_reviews",
    } <= tables


def test_migration_can_upgrade_the_same_database_twice(tmp_path: Path) -> None:
    database = tmp_path / "state.sqlite3"

    upgrade_database(database)
    upgrade_database(database)

    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT version_num FROM alembic_version").fetchone() == (
            "0006_feature_references",
        )


def test_phase_one_database_upgrades_without_losing_runs(tmp_path: Path, project_config) -> None:
    database = tmp_path / "state.sqlite3"
    upgrade_database(database, revision="0001_phase1")
    with sqlite3.connect(database) as connection:
        connection.execute(
            "INSERT INTO projects (id, name, root_path, created_at) VALUES (?, ?, ?, ?)",
            ("project", "Existing", str(tmp_path), "2026-09-14 00:00:00"),
        )
        connection.execute(
            "INSERT INTO roles (id, project_id, name, storage_state) VALUES (?, ?, ?, ?)",
            ("role", "project", "admin", None),
        )
        connection.execute(
            """INSERT INTO runs
               (id, project_id, role_id, procedure_name, status, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            ("run", "project", "role", "Existing run", "completed", "2026-09-14", "2026-09-14"),
        )

    upgrade_database(database)

    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT procedure_name, stage FROM runs WHERE id = 'run'").fetchone() == (
            "Existing run",
            "capture",
        )


def test_phase_three_database_upgrades_without_losing_workflow_revisions(tmp_path: Path) -> None:
    database = tmp_path / "state.sqlite3"
    upgrade_database(database, revision="0003_phase3")
    with sqlite3.connect(database) as connection:
        connection.execute(
            "INSERT INTO projects (id, name, root_path, created_at) VALUES (?, ?, ?, ?)",
            ("project", "Existing", str(tmp_path), "2026-09-15"),
        )
        connection.execute(
            "INSERT INTO roles (id, project_id, name, storage_state) VALUES (?, ?, ?, ?)",
            ("role", "project", "admin", None),
        )
        connection.execute(
            "INSERT INTO workflows (id, project_id, workflow_key, title, created_at) VALUES (?, ?, ?, ?, ?)",
            ("workflow", "project", "existing", "Existing workflow", "2026-09-15"),
        )
        connection.execute(
            """INSERT INTO workflow_revisions
               (id, workflow_id, role_id, parent_revision_id, version, content_hash, definition_json, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            ("revision", "workflow", "role", None, 1, "0" * 64, "{}", "2026-09-15"),
        )

    upgrade_database(database)

    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT id, version FROM workflow_revisions WHERE id = 'revision'").fetchone() == (
            "revision",
            1,
        )


def test_project_lock_prevents_concurrent_runner(repository, tmp_path, project_config) -> None:
    project_id, roles = repository.register_project(tmp_path, project_config)
    first = repository.create_run(project_id, roles["admin"], "first")
    second = repository.create_run(project_id, roles["admin"], "second")
    repository.acquire_project_lock(project_id, first.id)

    with pytest.raises(ProjectBusyError):
        repository.acquire_project_lock(project_id, second.id)

    repository.release_project_lock(project_id, first.id)
    repository.acquire_project_lock(project_id, second.id)


def test_recovery_marks_executing_attempt_uncertain(repository, tmp_path, project_config, monkeypatch) -> None:
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
        ObservationDraft(url="http://127.0.0.1:8765", title="Test", aria_snapshot="body", screenshot=b"png"),
        aria.id,
        screenshot.id,
    )
    attempt = repository.create_attempt(run.id, 1, action, observation.id)
    from web2doc.domain.models import AttemptStatus

    repository.set_attempt_status(attempt.id, AttemptStatus.EXECUTING)

    monkeypatch.setattr("web2doc.storage.repository.process_is_alive", lambda _pid: False)
    result = repository.recover_interrupted(project_id)

    assert result == {"attempts_marked_uncertain": 1, "runs_paused": 1}
    assert repository.list_attempts(run.id)[0].status == "uncertain"
    assert repository.get_run(run.id).status == "paused"


def test_recovery_refuses_to_clear_a_live_worker(repository, tmp_path, project_config) -> None:
    project_id, roles = repository.register_project(tmp_path, project_config)
    run = repository.create_run(project_id, roles["admin"], "active")
    repository.acquire_project_lock(project_id, run.id)

    with pytest.raises(ProjectBusyError, match="alive"):
        repository.recover_interrupted(project_id)


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
