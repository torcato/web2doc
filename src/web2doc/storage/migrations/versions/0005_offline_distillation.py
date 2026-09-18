"""Add immutable capture manifests and offline processing records."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005_offline_distillation"
down_revision: str | None = "0004_phase4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "capture_manifests",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("run_id", sa.String(36), sa.ForeignKey("runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("schema_version", sa.Integer(), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("content_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("run_id", "version", name="uq_capture_manifest_version"),
        sa.UniqueConstraint("run_id", "content_hash", name="uq_capture_manifest_hash"),
    )
    op.create_table(
        "processing_attempts",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "manifest_id",
            sa.String(36),
            sa.ForeignKey("capture_manifests.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("stage", sa.String(40), nullable=False),
        sa.Column("processor_name", sa.String(120), nullable=False),
        sa.Column("configuration_hash", sa.String(64), nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("error", sa.Text()),
        sa.Column("output_json", sa.Text()),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
    )
    op.create_index(
        "ix_processing_attempt_lookup",
        "processing_attempts",
        ["manifest_id", "stage", "processor_name", "configuration_hash", "status"],
    )
    op.create_table(
        "distilled_features",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "processing_attempt_id",
            sa.String(36),
            sa.ForeignKey("processing_attempts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("feature_key", sa.String(64), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("evidence_json", sa.Text(), nullable=False),
        sa.Column("unresolved_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "processing_attempt_id", "feature_key", name="uq_distilled_feature_attempt_key"
        ),
    )


def downgrade() -> None:
    op.drop_table("distilled_features")
    op.drop_index("ix_processing_attempt_lookup", table_name="processing_attempts")
    op.drop_table("processing_attempts")
    op.drop_table("capture_manifests")
