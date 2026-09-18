"""Add observed feature-reference revisions and reviews."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006_feature_references"
down_revision: str | None = "0005_offline_distillation"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "feature_reference_revisions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("project_id", sa.String(36), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("role_id", sa.String(36), sa.ForeignKey("roles.id", ondelete="RESTRICT"), nullable=False),
        sa.Column(
            "processing_attempt_id",
            sa.String(36),
            sa.ForeignKey("processing_attempts.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("reference_key", sa.String(200), nullable=False),
        sa.Column(
            "parent_revision_id",
            sa.String(36),
            sa.ForeignKey("feature_reference_revisions.id", ondelete="SET NULL"),
        ),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("source_kind", sa.String(30), nullable=False),
        sa.Column("content_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "project_id", "role_id", "reference_key", "version",
            name="uq_feature_reference_version",
        ),
        sa.UniqueConstraint(
            "project_id", "role_id", "reference_key", "content_hash",
            name="uq_feature_reference_hash",
        ),
    )
    op.create_table(
        "feature_reference_reviews",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "feature_reference_revision_id",
            sa.String(36),
            sa.ForeignKey("feature_reference_revisions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("decision", sa.String(20), nullable=False),
        sa.Column("reviewer", sa.String(200), nullable=False),
        sa.Column("notes", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("feature_reference_reviews")
    op.drop_table("feature_reference_revisions")
