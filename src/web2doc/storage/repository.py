from __future__ import annotations

import json
import os
from collections.abc import Sequence
from hashlib import sha256
from pathlib import Path
from typing import Any

from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from web2doc.discovery.models import CandidateAction, FrontierStatus, PlannerUsage, StateIdentity
from web2doc.domain.models import (
    Action,
    ArtifactDraft,
    AttemptStatus,
    DiscoveryLimits,
    DiscoveryMode,
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
    FeatureRow,
    FixtureReceiptRow,
    FrontierItemRow,
    ObservationRow,
    PredicateResultRow,
    ProjectLockRow,
    ProjectRow,
    RoleRow,
    RunRow,
    StateRow,
    TransitionRow,
    UsageEventRow,
    VerificationRow,
    WorkflowRevisionRow,
    WorkflowRow,
    WorkflowStepRow,
    make_engine,
)
from web2doc.verification.models import (
    FixtureReceiptDraft,
    OutcomePredicate,
    PredicateResultDraft,
    VerificationStatus,
    WorkflowDefinition,
    WorkflowRevision,
)


class ProjectBusyError(RuntimeError):
    pass


def process_is_alive(process_id: int) -> bool:
    try:
        os.kill(process_id, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


class Repository:
    def __init__(self, database_path: Path) -> None:
        self.engine = make_engine(database_path)
        self.sessions = sessionmaker(self.engine, expire_on_commit=False)

    def close(self) -> None:
        self.engine.dispose()

    def register_project(self, root: Path, config: ProjectConfig) -> tuple[str, dict[str, str]]:
        canonical_root = str(root.resolve())
        with self.sessions.begin() as session:
            project = session.scalar(select(ProjectRow).where(ProjectRow.root_path == canonical_root))
            if project is None:
                project = ProjectRow(id=new_id(), name=config.name, root_path=canonical_root, created_at=utc_now())
                session.add(project)
                session.flush()
            else:
                project.name = config.name

            existing = {
                row.name: row for row in session.scalars(select(RoleRow).where(RoleRow.project_id == project.id))
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

    def create_run(
        self,
        project_id: str,
        role_id: str,
        procedure_name: str,
        *,
        stage: str = "capture",
        scenario: str = "default",
        discovery_mode: DiscoveryMode | None = None,
        limits: DiscoveryLimits | None = None,
    ) -> RunRow:
        now = utc_now()
        run = RunRow(
            id=new_id(),
            project_id=project_id,
            role_id=role_id,
            procedure_name=procedure_name,
            status=RunStatus.QUEUED,
            stage=stage,
            scenario=scenario,
            discovery_mode=discovery_mode,
            limits_json=limits.model_dump_json() if limits is not None else None,
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
        self,
        run_id: str,
        sequence: int,
        action: Action,
        before_observation_id: str | None,
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

    def next_attempt_sequence(self, run_id: str) -> int:
        with self.sessions() as session:
            maximum = session.scalar(
                select(func.max(ActionAttemptRow.sequence)).where(ActionAttemptRow.run_id == run_id)
            )
            return int(maximum or 0) + 1

    def add_state(
        self,
        *,
        project_id: str,
        role_id: str,
        scenario: str,
        observation_id: str,
        identity: StateIdentity,
    ) -> tuple[StateRow, bool]:
        with self.sessions.begin() as session:
            state = session.scalar(
                select(StateRow).where(
                    StateRow.project_id == project_id,
                    StateRow.role_id == role_id,
                    StateRow.scenario == scenario,
                    StateRow.fingerprint == identity.fingerprint,
                    StateRow.algorithm_version == identity.algorithm_version,
                )
            )
            created = state is None
            if state is None:
                state = StateRow(
                    id=new_id(),
                    project_id=project_id,
                    role_id=role_id,
                    scenario=scenario,
                    fingerprint=identity.fingerprint,
                    algorithm_version=identity.algorithm_version,
                    route=identity.route,
                    normalized_structure=identity.normalized_structure,
                    representative_observation_id=observation_id,
                    created_at=utc_now(),
                )
                session.add(state)
                session.flush()
            observation = session.get(ObservationRow, observation_id)
            if observation is None:
                raise KeyError(f"observation not found: {observation_id}")
            observation.state_id = state.id
            return state, created

    def add_transition(
        self,
        *,
        run_id: str,
        source_state_id: str,
        target_state_id: str,
        attempt_id: str,
    ) -> TransitionRow:
        row = TransitionRow(
            id=new_id(),
            run_id=run_id,
            source_state_id=source_state_id,
            target_state_id=target_state_id,
            attempt_id=attempt_id,
            created_at=utc_now(),
        )
        with self.sessions.begin() as session:
            session.add(row)
        return row

    def enqueue_frontier(
        self,
        *,
        run_id: str,
        state_id: str,
        candidate: CandidateAction,
        path: list[Action],
        rationale: str,
        priority: int,
        depth: int,
    ) -> FrontierItemRow:
        with self.sessions.begin() as session:
            existing = session.scalar(
                select(FrontierItemRow).where(
                    FrontierItemRow.run_id == run_id,
                    FrontierItemRow.state_id == state_id,
                    FrontierItemRow.action_signature == candidate.signature,
                )
            )
            if existing is not None:
                if existing.status == FrontierStatus.PENDING:
                    existing.priority = max(existing.priority, priority)
                return existing
            now = utc_now()
            row = FrontierItemRow(
                id=new_id(),
                run_id=run_id,
                state_id=state_id,
                action_signature=candidate.signature,
                action_json=candidate.action.model_dump_json(),
                path_json=json.dumps([action.model_dump(mode="json") for action in path]),
                label=candidate.label,
                rationale=rationale,
                priority=priority,
                depth=depth,
                status=FrontierStatus.PENDING,
                created_at=now,
                updated_at=now,
            )
            session.add(row)
            return row

    def next_frontier(self, run_id: str, *, state_id: str | None = None) -> FrontierItemRow | None:
        with self.sessions() as session:
            statement = select(FrontierItemRow).where(
                FrontierItemRow.run_id == run_id,
                FrontierItemRow.status == FrontierStatus.PENDING,
            )
            if state_id is not None:
                statement = statement.where(FrontierItemRow.state_id == state_id)
            return session.scalar(
                statement.order_by(FrontierItemRow.priority.desc(), FrontierItemRow.created_at).limit(1)
            )

    def frontier_exists_for_state(self, run_id: str, state_id: str) -> bool:
        with self.sessions() as session:
            return (
                session.scalar(
                    select(func.count(FrontierItemRow.id)).where(
                        FrontierItemRow.run_id == run_id,
                        FrontierItemRow.state_id == state_id,
                    )
                )
                or 0
            ) > 0

    def set_frontier_status(
        self,
        frontier_id: str,
        status: FrontierStatus,
        *,
        reason: str | None = None,
        attempt_id: str | None = None,
    ) -> None:
        with self.sessions.begin() as session:
            row = session.get(FrontierItemRow, frontier_id)
            if row is None:
                raise KeyError(f"frontier item not found: {frontier_id}")
            row.status = status
            row.reason = reason
            row.attempt_id = attempt_id
            row.updated_at = utc_now()

    def skip_pending_frontier(self, run_id: str, reason: str) -> int:
        with self.sessions.begin() as session:
            result = session.execute(
                update(FrontierItemRow)
                .where(
                    FrontierItemRow.run_id == run_id,
                    FrontierItemRow.status == FrontierStatus.PENDING,
                )
                .values(status=FrontierStatus.SKIPPED, reason=reason, updated_at=utc_now())
            )
            return int(result.rowcount)  # type: ignore[attr-defined]

    def add_feature(
        self,
        *,
        run_id: str,
        role_id: str,
        state_id: str,
        observation_id: str,
        title: str,
        description: str,
        confidence: float,
        unresolved: list[str] | None = None,
    ) -> FeatureRow:
        with self.sessions.begin() as session:
            existing = session.scalar(select(FeatureRow).where(FeatureRow.run_id == run_id, FeatureRow.title == title))
            if existing is not None:
                existing.confidence = max(existing.confidence, confidence)
                if description and not existing.description:
                    existing.description = description
                return existing
            row = FeatureRow(
                id=new_id(),
                run_id=run_id,
                role_id=role_id,
                state_id=state_id,
                observation_id=observation_id,
                title=title,
                description=description,
                confidence=confidence,
                unresolved_json=json.dumps(unresolved or []),
                created_at=utc_now(),
            )
            session.add(row)
            return row

    def add_usage_event(self, run_id: str, model_name: str, usage: PlannerUsage, duration_ms: int) -> None:
        with self.sessions.begin() as session:
            session.add(
                UsageEventRow(
                    id=new_id(),
                    run_id=run_id,
                    model_name=model_name,
                    input_tokens=usage.input_tokens,
                    output_tokens=usage.output_tokens,
                    usage_reported=int(usage.usage_reported),
                    duration_ms=duration_ms,
                    created_at=utc_now(),
                )
            )

    def add_workflow_revision(
        self,
        *,
        project_id: str,
        role_id: str,
        definition: WorkflowDefinition,
    ) -> WorkflowRevision:
        dumped = definition.model_dump(mode="json")
        canonical = json.dumps(dumped, sort_keys=True, separators=(",", ":"))
        hashable = definition.model_dump(mode="json")
        for step in hashable["steps"]:
            step["action"].pop("id", None)
        content_hash = sha256(json.dumps(hashable, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        with self.sessions.begin() as session:
            workflow = session.scalar(
                select(WorkflowRow).where(
                    WorkflowRow.project_id == project_id,
                    WorkflowRow.workflow_key == definition.workflow_key,
                )
            )
            if workflow is None:
                workflow = WorkflowRow(
                    id=new_id(),
                    project_id=project_id,
                    workflow_key=definition.workflow_key,
                    title=definition.title,
                    created_at=utc_now(),
                )
                session.add(workflow)
                session.flush()
            else:
                workflow.title = definition.title
            existing = session.scalar(
                select(WorkflowRevisionRow).where(
                    WorkflowRevisionRow.workflow_id == workflow.id,
                    WorkflowRevisionRow.content_hash == content_hash,
                )
            )
            if existing is not None:
                return WorkflowRevision(
                    id=existing.id,
                    workflow_id=workflow.id,
                    version=existing.version,
                    content_hash=existing.content_hash,
                    definition=WorkflowDefinition.model_validate_json(existing.definition_json),
                )
            latest = session.scalar(
                select(WorkflowRevisionRow)
                .where(WorkflowRevisionRow.workflow_id == workflow.id)
                .order_by(WorkflowRevisionRow.version.desc())
                .limit(1)
            )
            revision = WorkflowRevisionRow(
                id=new_id(),
                workflow_id=workflow.id,
                role_id=role_id,
                parent_revision_id=latest.id if latest is not None else None,
                version=(latest.version + 1) if latest is not None else 1,
                content_hash=content_hash,
                definition_json=canonical,
                created_at=utc_now(),
            )
            session.add(revision)
            session.flush()
            for sequence, step in enumerate(definition.steps, start=1):
                session.add(
                    WorkflowStepRow(
                        id=new_id(),
                        revision_id=revision.id,
                        sequence=sequence,
                        action_json=step.action.model_dump_json(),
                        expected_json=json.dumps(
                            [item.model_dump(mode="json") for item in step.expected],
                            sort_keys=True,
                        ),
                    )
                )
            return WorkflowRevision(
                id=revision.id,
                workflow_id=workflow.id,
                version=revision.version,
                content_hash=content_hash,
                definition=definition,
            )

    def get_workflow_revision(self, revision_id: str) -> WorkflowRevision:
        with self.sessions() as session:
            row = session.get(WorkflowRevisionRow, revision_id)
            if row is None:
                raise KeyError(f"workflow revision not found: {revision_id}")
            return WorkflowRevision(
                id=row.id,
                workflow_id=row.workflow_id,
                version=row.version,
                content_hash=row.content_hash,
                definition=WorkflowDefinition.model_validate_json(row.definition_json),
            )

    def add_fixture_receipt(self, project_id: str, draft: FixtureReceiptDraft) -> FixtureReceiptRow:
        row = FixtureReceiptRow(
            id=new_id(),
            project_id=project_id,
            adapter_name=draft.adapter_name,
            scenario=draft.scenario,
            application_version=draft.application_version,
            payload_json=json.dumps(draft.payload, sort_keys=True),
            prepared_at=utc_now(),
        )
        with self.sessions.begin() as session:
            session.add(row)
        return row

    def mark_fixture_reset(self, receipt_id: str) -> None:
        with self.sessions.begin() as session:
            row = session.get(FixtureReceiptRow, receipt_id)
            if row is None:
                raise KeyError(f"fixture receipt not found: {receipt_id}")
            row.reset_at = utc_now()

    def create_verification(
        self, workflow_revision_id: str, run_id: str, fixture_receipt_id: str | None
    ) -> VerificationRow:
        row = VerificationRow(
            id=new_id(),
            workflow_revision_id=workflow_revision_id,
            run_id=run_id,
            fixture_receipt_id=fixture_receipt_id,
            status=VerificationStatus.RUNNING,
            started_at=utc_now(),
        )
        with self.sessions.begin() as session:
            session.add(row)
        return row

    def set_verification_status(
        self, verification_id: str, status: VerificationStatus, reason: str | None = None
    ) -> None:
        with self.sessions.begin() as session:
            row = session.get(VerificationRow, verification_id)
            if row is None:
                raise KeyError(f"verification not found: {verification_id}")
            row.status = status
            row.reason = reason
            if status in {VerificationStatus.PASSED, VerificationStatus.FAILED, VerificationStatus.INCONCLUSIVE}:
                row.completed_at = utc_now()

    def add_predicate_result(
        self,
        *,
        verification_id: str,
        phase: str,
        step_sequence: int,
        predicate_index: int,
        predicate: OutcomePredicate,
        result: PredicateResultDraft,
        observation_id: str | None,
    ) -> PredicateResultRow:
        row = PredicateResultRow(
            id=new_id(),
            verification_id=verification_id,
            phase=phase,
            step_sequence=step_sequence,
            predicate_index=predicate_index,
            predicate_json=predicate.model_dump_json(),
            status=result.status,
            message=result.message,
            observed_json=json.dumps(result.observed, sort_keys=True),
            observation_id=observation_id,
            created_at=utc_now(),
        )
        with self.sessions.begin() as session:
            session.add(row)
        return row

    def verification_report(self, verification_id: str) -> dict[str, object]:
        with self.sessions() as session:
            verification = session.get(VerificationRow, verification_id)
            if verification is None:
                raise KeyError(f"verification not found: {verification_id}")
            results = tuple(
                session.scalars(
                    select(PredicateResultRow)
                    .where(PredicateResultRow.verification_id == verification_id)
                    .order_by(
                        PredicateResultRow.step_sequence,
                        PredicateResultRow.phase,
                        PredicateResultRow.predicate_index,
                    )
                )
            )
            return {
                "id": verification.id,
                "run_id": verification.run_id,
                "workflow_revision_id": verification.workflow_revision_id,
                "status": verification.status,
                "reason": verification.reason,
                "fixture_receipt_id": verification.fixture_receipt_id,
                "predicates": [
                    {
                        "phase": row.phase,
                        "step": row.step_sequence,
                        "status": row.status,
                        "message": row.message,
                        "observed": json.loads(row.observed_json),
                        "observation_id": row.observation_id,
                    }
                    for row in results
                ],
            }

    def reconciliation_receipt(self, workflow_revision_id: str) -> tuple[str, FixtureReceiptDraft] | None:
        with self.sessions() as session:
            receipt = session.scalar(
                select(FixtureReceiptRow)
                .join(VerificationRow, VerificationRow.fixture_receipt_id == FixtureReceiptRow.id)
                .join(RunRow, RunRow.id == VerificationRow.run_id)
                .join(ActionAttemptRow, ActionAttemptRow.run_id == RunRow.id)
                .where(
                    VerificationRow.workflow_revision_id == workflow_revision_id,
                    ActionAttemptRow.status == AttemptStatus.UNCERTAIN,
                    FixtureReceiptRow.reset_at.is_(None),
                )
                .order_by(FixtureReceiptRow.prepared_at.desc())
                .limit(1)
            )
            if receipt is None:
                return None
            return receipt.id, FixtureReceiptDraft(
                adapter_name=receipt.adapter_name,
                scenario=receipt.scenario,
                application_version=receipt.application_version,
                payload=json.loads(receipt.payload_json),
            )

    def uncertain_attempt_for_revision(self, workflow_revision_id: str, sequence: int) -> ActionAttemptRow | None:
        with self.sessions() as session:
            return session.scalar(
                select(ActionAttemptRow)
                .join(RunRow, RunRow.id == ActionAttemptRow.run_id)
                .join(VerificationRow, VerificationRow.run_id == RunRow.id)
                .where(
                    VerificationRow.workflow_revision_id == workflow_revision_id,
                    ActionAttemptRow.sequence == sequence,
                    ActionAttemptRow.status == AttemptStatus.UNCERTAIN,
                )
                .order_by(ActionAttemptRow.created_at.desc())
                .limit(1)
            )

    def recover_interrupted(self, project_id: str) -> dict[str, int]:
        recovered_attempts = 0
        paused_runs = 0
        with self.sessions.begin() as session:
            locks = tuple(session.scalars(select(ProjectLockRow).where(ProjectLockRow.project_id == project_id)))
            if any(process_is_alive(lock.process_id) for lock in locks):
                raise ProjectBusyError("cannot recover while the recorded worker process is alive")
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
                attempt.error = "worker stopped while browser action was executing; reconcile before retry"
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
                "stage": run.stage,
                "scenario": run.scenario,
                "discovery_mode": run.discovery_mode,
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

    def discovery_report(self, run_id: str) -> dict[str, object]:
        with self.sessions() as session:
            run = session.get(RunRow, run_id)
            if run is None:
                raise KeyError(f"run not found: {run_id}")
            state_ids = {
                value
                for value in session.scalars(
                    select(ObservationRow.state_id).where(
                        ObservationRow.run_id == run_id,
                        ObservationRow.state_id.is_not(None),
                    )
                )
                if value is not None
            }
            states = tuple(
                session.scalars(select(StateRow).where(StateRow.id.in_(state_ids)).order_by(StateRow.created_at))
            )
            transitions = tuple(session.scalars(select(TransitionRow).where(TransitionRow.run_id == run_id)))
            frontier = tuple(
                session.scalars(
                    select(FrontierItemRow)
                    .where(FrontierItemRow.run_id == run_id)
                    .order_by(FrontierItemRow.priority.desc())
                )
            )
            features = tuple(
                session.scalars(select(FeatureRow).where(FeatureRow.run_id == run_id).order_by(FeatureRow.title))
            )
            usage = tuple(session.scalars(select(UsageEventRow).where(UsageEventRow.run_id == run_id)))
            status_counts: dict[str, int] = {}
            for item in frontier:
                status_counts[item.status] = status_counts.get(item.status, 0) + 1
            return {
                "run": {
                    "id": run.id,
                    "status": run.status,
                    "stop_reason": run.stop_reason,
                    "mode": run.discovery_mode,
                    "scenario": run.scenario,
                },
                "coverage": {
                    "states": len(states),
                    "transitions": len(transitions),
                    "frontier": status_counts,
                    "model_calls": len(usage),
                    "input_tokens": sum(event.input_tokens for event in usage),
                    "output_tokens": sum(event.output_tokens for event in usage),
                },
                "states": [
                    {
                        "id": state.id,
                        "route": state.route,
                        "fingerprint": state.fingerprint,
                        "algorithm_version": state.algorithm_version,
                    }
                    for state in states
                ],
                "transitions": [
                    {
                        "id": transition.id,
                        "source_state_id": transition.source_state_id,
                        "target_state_id": transition.target_state_id,
                        "attempt_id": transition.attempt_id,
                    }
                    for transition in transitions
                ],
                "features": [
                    {
                        "title": feature.title,
                        "description": feature.description,
                        "confidence": feature.confidence,
                        "state_id": feature.state_id,
                        "observation_id": feature.observation_id,
                        "unresolved": json.loads(feature.unresolved_json),
                    }
                    for feature in features
                ],
                "unexplored": [
                    {
                        "label": item.label,
                        "status": item.status,
                        "reason": item.reason,
                        "depth": item.depth,
                    }
                    for item in frontier
                    if item.status != FrontierStatus.EXPLORED
                ],
            }

    def explored_workflow_candidates(self, run_id: str) -> list[dict[str, Any]]:
        with self.sessions() as session:
            items = tuple(
                session.scalars(
                    select(FrontierItemRow)
                    .where(
                        FrontierItemRow.run_id == run_id,
                        FrontierItemRow.status == FrontierStatus.EXPLORED,
                        FrontierItemRow.attempt_id.is_not(None),
                    )
                    .order_by(FrontierItemRow.created_at)
                )
            )
            values: list[dict[str, Any]] = []
            for item in items:
                transition = session.scalar(select(TransitionRow).where(TransitionRow.attempt_id == item.attempt_id))
                target = session.get(StateRow, transition.target_state_id) if transition else None
                if target is None:
                    continue
                features = tuple(
                    session.scalars(
                        select(FeatureRow).where(
                            FeatureRow.run_id == run_id,
                            FeatureRow.state_id == target.id,
                        )
                    )
                )
                values.append(
                    {
                        "label": item.label,
                        "path": json.loads(item.path_json),
                        "action": json.loads(item.action_json),
                        "target_route": target.route,
                        "feature_ids": [feature.id for feature in features],
                    }
                )
            return values
