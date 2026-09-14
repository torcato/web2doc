from __future__ import annotations

from datetime import datetime
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint, create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class ProjectRow(Base):
    __tablename__ = "projects"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    root_path: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    roles: Mapped[list[RoleRow]] = relationship(back_populates="project", cascade="all, delete-orphan")


class RoleRow(Base):
    __tablename__ = "roles"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    storage_state: Mapped[str | None] = mapped_column(Text)

    project: Mapped[ProjectRow] = relationship(back_populates="roles")


class RunRow(Base):
    __tablename__ = "runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    role_id: Mapped[str] = mapped_column(ForeignKey("roles.id", ondelete="RESTRICT"), nullable=False)
    procedure_name: Mapped[str] = mapped_column(String(300), nullable=False)
    status: Mapped[str] = mapped_column(String(40), nullable=False)
    stop_reason: Mapped[str | None] = mapped_column(Text)
    stage: Mapped[str] = mapped_column(String(40), nullable=False, default="capture")
    scenario: Mapped[str] = mapped_column(String(100), nullable=False, default="default")
    discovery_mode: Mapped[str | None] = mapped_column(String(30))
    limits_json: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ArtifactRow(Base):
    __tablename__ = "artifacts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"), nullable=False)
    relative_path: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    media_type: Mapped[str] = mapped_column(String(200), nullable=False)
    sensitivity: Mapped[str] = mapped_column(String(20), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ObservationRow(Base):
    __tablename__ = "observations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"), nullable=False)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    aria_artifact_id: Mapped[str] = mapped_column(ForeignKey("artifacts.id", ondelete="RESTRICT"), nullable=False)
    screenshot_artifact_id: Mapped[str] = mapped_column(ForeignKey("artifacts.id", ondelete="RESTRICT"), nullable=False)
    state_id: Mapped[str | None] = mapped_column(ForeignKey("states.id", ondelete="SET NULL"))
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ActionAttemptRow(Base):
    __tablename__ = "action_attempts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"), nullable=False)
    action_id: Mapped[str] = mapped_column(String(36), nullable=False)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    action_kind: Mapped[str] = mapped_column(String(30), nullable=False)
    effect: Mapped[str] = mapped_column(String(20), nullable=False)
    operation_id: Mapped[str | None] = mapped_column(String(200))
    payload_json: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False)
    policy_reason: Mapped[str | None] = mapped_column(Text)
    error: Mapped[str | None] = mapped_column(Text)
    result_json: Mapped[str | None] = mapped_column(Text)
    before_observation_id: Mapped[str | None] = mapped_column(ForeignKey("observations.id", ondelete="RESTRICT"))
    after_observation_id: Mapped[str | None] = mapped_column(ForeignKey("observations.id", ondelete="RESTRICT"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ProjectLockRow(Base):
    __tablename__ = "project_locks"

    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), primary_key=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"), nullable=False)
    process_id: Mapped[int] = mapped_column(Integer, nullable=False)
    acquired_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class StateRow(Base):
    __tablename__ = "states"
    __table_args__ = (
        UniqueConstraint(
            "project_id",
            "role_id",
            "scenario",
            "fingerprint",
            "algorithm_version",
            name="uq_state_identity",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    role_id: Mapped[str] = mapped_column(ForeignKey("roles.id", ondelete="CASCADE"), nullable=False)
    scenario: Mapped[str] = mapped_column(String(100), nullable=False)
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    algorithm_version: Mapped[str] = mapped_column(String(40), nullable=False)
    route: Mapped[str] = mapped_column(Text, nullable=False)
    normalized_structure: Mapped[str] = mapped_column(Text, nullable=False)
    representative_observation_id: Mapped[str] = mapped_column(
        ForeignKey("observations.id", ondelete="RESTRICT"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class TransitionRow(Base):
    __tablename__ = "transitions"
    __table_args__ = (UniqueConstraint("run_id", "attempt_id", name="uq_transition_attempt"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"), nullable=False)
    source_state_id: Mapped[str] = mapped_column(ForeignKey("states.id", ondelete="RESTRICT"), nullable=False)
    target_state_id: Mapped[str] = mapped_column(ForeignKey("states.id", ondelete="RESTRICT"), nullable=False)
    attempt_id: Mapped[str] = mapped_column(ForeignKey("action_attempts.id", ondelete="CASCADE"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class FrontierItemRow(Base):
    __tablename__ = "frontier_items"
    __table_args__ = (UniqueConstraint("run_id", "state_id", "action_signature", name="uq_frontier_candidate"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"), nullable=False)
    state_id: Mapped[str] = mapped_column(ForeignKey("states.id", ondelete="CASCADE"), nullable=False)
    action_signature: Mapped[str] = mapped_column(String(64), nullable=False)
    action_json: Mapped[str] = mapped_column(Text, nullable=False)
    path_json: Mapped[str] = mapped_column(Text, nullable=False)
    label: Mapped[str] = mapped_column(String(300), nullable=False)
    rationale: Mapped[str] = mapped_column(Text, nullable=False)
    priority: Mapped[int] = mapped_column(Integer, nullable=False)
    depth: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False)
    reason: Mapped[str | None] = mapped_column(Text)
    attempt_id: Mapped[str | None] = mapped_column(ForeignKey("action_attempts.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class FeatureRow(Base):
    __tablename__ = "features"
    __table_args__ = (UniqueConstraint("run_id", "title", name="uq_feature_run_title"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"), nullable=False)
    role_id: Mapped[str] = mapped_column(ForeignKey("roles.id", ondelete="RESTRICT"), nullable=False)
    state_id: Mapped[str] = mapped_column(ForeignKey("states.id", ondelete="RESTRICT"), nullable=False)
    observation_id: Mapped[str] = mapped_column(ForeignKey("observations.id", ondelete="RESTRICT"), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    unresolved_json: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class UsageEventRow(Base):
    __tablename__ = "usage_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"), nullable=False)
    model_name: Mapped[str] = mapped_column(String(200), nullable=False)
    input_tokens: Mapped[int] = mapped_column(Integer, nullable=False)
    output_tokens: Mapped[int] = mapped_column(Integer, nullable=False)
    usage_reported: Mapped[int] = mapped_column(Integer, nullable=False)
    duration_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class WorkflowRow(Base):
    __tablename__ = "workflows"
    __table_args__ = (UniqueConstraint("project_id", "workflow_key", name="uq_workflow_project_key"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    workflow_key: Mapped[str] = mapped_column(String(120), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class WorkflowRevisionRow(Base):
    __tablename__ = "workflow_revisions"
    __table_args__ = (
        UniqueConstraint("workflow_id", "version", name="uq_workflow_revision_version"),
        UniqueConstraint("workflow_id", "content_hash", name="uq_workflow_revision_hash"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    workflow_id: Mapped[str] = mapped_column(ForeignKey("workflows.id", ondelete="CASCADE"), nullable=False)
    role_id: Mapped[str] = mapped_column(ForeignKey("roles.id", ondelete="RESTRICT"), nullable=False)
    parent_revision_id: Mapped[str | None] = mapped_column(ForeignKey("workflow_revisions.id", ondelete="SET NULL"))
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    definition_json: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class WorkflowStepRow(Base):
    __tablename__ = "workflow_steps"
    __table_args__ = (UniqueConstraint("revision_id", "sequence", name="uq_workflow_step_sequence"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    revision_id: Mapped[str] = mapped_column(ForeignKey("workflow_revisions.id", ondelete="CASCADE"), nullable=False)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    action_json: Mapped[str] = mapped_column(Text, nullable=False)
    expected_json: Mapped[str] = mapped_column(Text, nullable=False)


class FixtureReceiptRow(Base):
    __tablename__ = "fixture_receipts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    adapter_name: Mapped[str] = mapped_column(String(100), nullable=False)
    scenario: Mapped[str] = mapped_column(String(100), nullable=False)
    application_version: Mapped[str | None] = mapped_column(String(100))
    payload_json: Mapped[str] = mapped_column(Text, nullable=False)
    prepared_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    reset_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class VerificationRow(Base):
    __tablename__ = "verifications"
    __table_args__ = (UniqueConstraint("run_id", name="uq_verification_run"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    workflow_revision_id: Mapped[str] = mapped_column(
        ForeignKey("workflow_revisions.id", ondelete="RESTRICT"), nullable=False
    )
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"), nullable=False)
    fixture_receipt_id: Mapped[str | None] = mapped_column(ForeignKey("fixture_receipts.id", ondelete="SET NULL"))
    status: Mapped[str] = mapped_column(String(30), nullable=False)
    reason: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class PredicateResultRow(Base):
    __tablename__ = "predicate_results"
    __table_args__ = (
        UniqueConstraint("verification_id", "phase", "step_sequence", "predicate_index", name="uq_predicate_result"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    verification_id: Mapped[str] = mapped_column(ForeignKey("verifications.id", ondelete="CASCADE"), nullable=False)
    phase: Mapped[str] = mapped_column(String(30), nullable=False)
    step_sequence: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    predicate_index: Mapped[int] = mapped_column(Integer, nullable=False)
    predicate_json: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    observed_json: Mapped[str] = mapped_column(Text, nullable=False)
    observation_id: Mapped[str | None] = mapped_column(ForeignKey("observations.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


def make_engine(database_path: Path) -> Engine:
    database_path.parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(f"sqlite:///{database_path}")

    @event.listens_for(engine, "connect")
    def enable_foreign_keys(dbapi_connection: object, _connection_record: object) -> None:
        cursor = dbapi_connection.cursor()  # type: ignore[attr-defined]
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    return engine


def upgrade_database(database_path: Path, *, revision: str = "head") -> None:
    database_path.parent.mkdir(parents=True, exist_ok=True)
    migration_root = Path(__file__).with_name("migrations")
    config = Config()
    config.set_main_option("script_location", str(migration_root))
    config.set_main_option("sqlalchemy.url", f"sqlite:///{database_path}")
    command.upgrade(config, revision)
