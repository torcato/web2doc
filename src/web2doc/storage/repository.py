from __future__ import annotations

import json
import os
from collections.abc import Sequence
from pathlib import Path

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from web2doc.domain.models import (
    Action,
    ArtifactDraft,
    AttemptStatus,
    ExecutionResult,
    ObservationDraft,
    ProjectConfig,
    RunStatus,
    new_id,
    utc_now,
)
from web2doc.storage.database import (
    ActionAttemptRow,
    ArtifactRow,
    ObservationRow,
    ProjectLockRow,
    ProjectRow,
    RoleRow,
    RunRow,
    make_engine,
)


class ProjectBusyError(RuntimeError):
    pass


class Repository:
    def __init__(self, database_path: Path) -> None:
        self.engine = make_engine(database_path)
        self.sessions = sessionmaker(self.engine, expire_on_commit=False)

    def close(self) -> None:
        self.engine.dispose()

    def register_project(self, root: Path, config: ProjectConfig) -> tuple[str, dict[str, str]]:
        canonical_root = str(root.resolve())
        with self.sessions.begin() as session:
            project = session.scalar(
                select(ProjectRow).where(ProjectRow.root_path == canonical_root)
            )
            if project is None:
                project = ProjectRow(
                    id=new_id(), name=config.name, root_path=canonical_root, created_at=utc_now()
                )
                session.add(project)
                session.flush()
            else:
                project.name = config.name

            existing = {
                row.name: row
                for row in session.scalars(select(RoleRow).where(RoleRow.project_id == project.id))
            }
            role_ids: dict[str, str] = {}
            for role_config in config.roles:
                role = existing.get(role_config.name)
                if role is None:
                    role = RoleRow(
                        id=new_id(),
                        project_id=project.id,
                        name=role_config.name,
                        storage_state=role_config.storage_state,
                    )
                    session.add(role)
                else:
                    role.storage_state = role_config.storage_state
                role_ids[role_config.name] = role.id
            return project.id, role_ids

    def create_run(self, project_id: str, role_id: str, procedure_name: str) -> RunRow:
        now = utc_now()
        run = RunRow(
            id=new_id(),
            project_id=project_id,
            role_id=role_id,
            procedure_name=procedure_name,
            status=RunStatus.QUEUED,
            created_at=now,
            updated_at=now,
        )
        with self.sessions.begin() as session:
            session.add(run)
        return run

    def get_run(self, run_id: str) -> RunRow | None:
        with self.sessions() as session:
            return session.get(RunRow, run_id)

    def set_run_status(self, run_id: str, status: RunStatus, reason: str | None = None) -> None:
        with self.sessions.begin() as session:
            row = session.get(RunRow, run_id)
            if row is None:
                raise KeyError(f"run not found: {run_id}")
            row.status = status
            row.stop_reason = reason
            row.updated_at = utc_now()

    def request_cancel(self, run_id: str) -> None:
        self.set_run_status(run_id, RunStatus.CANCELLED, "cancel requested")

    def acquire_project_lock(self, project_id: str, run_id: str) -> None:
        try:
            with self.sessions.begin() as session:
                session.add(
                    ProjectLockRow(
                        project_id=project_id,
                        run_id=run_id,
                        process_id=os.getpid(),
                        acquired_at=utc_now(),
                    )
                )
        except IntegrityError as exc:
            raise ProjectBusyError("project already has an active or unrecovered run") from exc

    def release_project_lock(self, project_id: str, run_id: str) -> None:
        with self.sessions.begin() as session:
            session.execute(
                delete(ProjectLockRow).where(
                    ProjectLockRow.project_id == project_id,
                    ProjectLockRow.run_id == run_id,
                )
            )

    def add_artifact(self, run_id: str, draft: ArtifactDraft) -> ArtifactRow:
        row = ArtifactRow(
            id=draft.id,
            run_id=run_id,
            relative_path=draft.relative_path,
            sha256=draft.sha256,
            media_type=draft.media_type,
            sensitivity=draft.sensitivity,
            size_bytes=draft.size_bytes,
            created_at=utc_now(),
        )
        with self.sessions.begin() as session:
            session.add(row)
        return row

    def add_observation(
        self,
        run_id: str,
        draft: ObservationDraft,
        aria_artifact_id: str,
        screenshot_artifact_id: str,
    ) -> ObservationRow:
        row = ObservationRow(
            id=new_id(),
            run_id=run_id,
            url=draft.url,
            title=draft.title,
            aria_artifact_id=aria_artifact_id,
            screenshot_artifact_id=screenshot_artifact_id,
            observed_at=draft.observed_at,
        )
        with self.sessions.begin() as session:
            session.add(row)
        return row

    def create_attempt(
        self, run_id: str, sequence: int, action: Action, before_observation_id: str
    ) -> ActionAttemptRow:
        row = ActionAttemptRow(
            id=new_id(),
            run_id=run_id,
            action_id=action.id,
            sequence=sequence,
            action_kind=action.kind,
            effect=action.effect,
            operation_id=action.operation_id,
            payload_json=action.model_dump_json(),
            status=AttemptStatus.PLANNED,
            before_observation_id=before_observation_id,
            created_at=utc_now(),
            updated_at=utc_now(),
        )
        with self.sessions.begin() as session:
            session.add(row)
        return row

    def set_attempt_status(
        self,
        attempt_id: str,
        status: AttemptStatus,
        *,
        policy_reason: str | None = None,
        error: str | None = None,
        result: ExecutionResult | None = None,
        after_observation_id: str | None = None,
    ) -> None:
        with self.sessions.begin() as session:
            row = session.get(ActionAttemptRow, attempt_id)
            if row is None:
                raise KeyError(f"attempt not found: {attempt_id}")
            row.status = status
            if policy_reason is not None:
                row.policy_reason = policy_reason
            if error is not None:
                row.error = error
            if result is not None:
                row.result_json = result.model_dump_json()
            if after_observation_id is not None:
                row.after_observation_id = after_observation_id
            row.updated_at = utc_now()

    def list_attempts(self, run_id: str) -> Sequence[ActionAttemptRow]:
        with self.sessions() as session:
            return tuple(
                session.scalars(
                    select(ActionAttemptRow)
                    .where(ActionAttemptRow.run_id == run_id)
                    .order_by(ActionAttemptRow.sequence)
                )
            )

    def recover_interrupted(self, project_id: str) -> dict[str, int]:
        recovered_attempts = 0
        paused_runs = 0
        with self.sessions.begin() as session:
            executing = tuple(
                session.scalars(
                    select(ActionAttemptRow)
                    .join(RunRow, RunRow.id == ActionAttemptRow.run_id)
                    .where(
                        RunRow.project_id == project_id,
                        ActionAttemptRow.status == AttemptStatus.EXECUTING,
                    )
                )
            )
            for attempt in executing:
                attempt.status = AttemptStatus.UNCERTAIN
                attempt.error = (
                    "worker stopped while browser action was executing; reconcile before retry"
                )
                attempt.updated_at = utc_now()
                recovered_attempts += 1

            running = tuple(
                session.scalars(
                    select(RunRow).where(
                        RunRow.project_id == project_id,
                        RunRow.status.in_([RunStatus.RUNNING, RunStatus.QUEUED]),
                    )
                )
            )
            for run in running:
                run.status = RunStatus.PAUSED
                run.stop_reason = "recovered after interrupted worker"
                run.updated_at = utc_now()
                paused_runs += 1
            session.execute(delete(ProjectLockRow).where(ProjectLockRow.project_id == project_id))
        return {"attempts_marked_uncertain": recovered_attempts, "runs_paused": paused_runs}

    def run_summary(self, run_id: str) -> dict[str, object]:
        with self.sessions() as session:
            run = session.get(RunRow, run_id)
            if run is None:
                raise KeyError(f"run not found: {run_id}")
            attempts = tuple(
                session.scalars(
                    select(ActionAttemptRow)
                    .where(ActionAttemptRow.run_id == run_id)
                    .order_by(ActionAttemptRow.sequence)
                )
            )
            return {
                "id": run.id,
                "procedure": run.procedure_name,
                "status": run.status,
                "stop_reason": run.stop_reason,
                "attempts": [
                    {
                        "sequence": row.sequence,
                        "kind": row.action_kind,
                        "status": row.status,
                        "description": json.loads(row.payload_json)["description"],
                        "error": row.error,
                    }
                    for row in attempts
                ],
            }
