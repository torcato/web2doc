"""Add Phase 3 versioned workflows and verification evidence."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003_phase3"
down_revision: str | None = "0002_phase2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "workflows",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("project_id", sa.String(36), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("workflow_key", sa.String(120), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("project_id", "workflow_key", name="uq_workflow_project_key"),
    )
    op.create_table(
        "workflow_revisions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("workflow_id", sa.String(36), sa.ForeignKey("workflows.id", ondelete="CASCADE"), nullable=False),
        sa.Column("role_id", sa.String(36), sa.ForeignKey("roles.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("parent_revision_id", sa.String(36), sa.ForeignKey("workflow_revisions.id", ondelete="SET NULL")),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("definition_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("workflow_id", "version", name="uq_workflow_revision_version"),
        sa.UniqueConstraint("workflow_id", "content_hash", name="uq_workflow_revision_hash"),
    )
    op.create_table(
        "workflow_steps",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "revision_id", sa.String(36), sa.ForeignKey("workflow_revisions.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("action_json", sa.Text(), nullable=False),
        sa.Column("expected_json", sa.Text(), nullable=False),
        sa.UniqueConstraint("revision_id", "sequence", name="uq_workflow_step_sequence"),
    )
    op.create_table(
        "fixture_receipts",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("project_id", sa.String(36), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("adapter_name", sa.String(100), nullable=False),
        sa.Column("scenario", sa.String(100), nullable=False),
        sa.Column("application_version", sa.String(100)),
        sa.Column("payload_json", sa.Text(), nullable=False),
        sa.Column("prepared_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reset_at", sa.DateTime(timezone=True)),
    )
    op.create_table(
        "verifications",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "workflow_revision_id",
            sa.String(36),
            sa.ForeignKey("workflow_revisions.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("run_id", sa.String(36), sa.ForeignKey("runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("fixture_receipt_id", sa.String(36), sa.ForeignKey("fixture_receipts.id", ondelete="SET NULL")),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("reason", sa.Text()),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("run_id", name="uq_verification_run"),
    )
    op.create_table(
        "predicate_results",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "verification_id", sa.String(36), sa.ForeignKey("verifications.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("phase", sa.String(30), nullable=False),
        sa.Column("step_sequence", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("predicate_index", sa.Integer(), nullable=False),
        sa.Column("predicate_json", sa.Text(), nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("observed_json", sa.Text(), nullable=False),
        sa.Column("observation_id", sa.String(36), sa.ForeignKey("observations.id", ondelete="SET NULL")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("verification_id", "phase", "step_sequence", "predicate_index", name="uq_predicate_result"),
    )


def downgrade() -> None:
    op.drop_table("predicate_results")
    op.drop_table("verifications")
    op.drop_table("fixture_receipts")
    op.drop_table("workflow_steps")
    op.drop_table("workflow_revisions")
    op.drop_table("workflows")
