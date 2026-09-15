"""Add Phase 4 document, provenance, review, and export records."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004_phase4"
down_revision: str | None = "0003_phase3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "owner_sources",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("project_id", sa.String(36), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("source_kind", sa.String(30), nullable=False),
        sa.Column("label", sa.String(200), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "document_revisions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("workflow_revision_id", sa.String(36), sa.ForeignKey("workflow_revisions.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("verification_id", sa.String(36), sa.ForeignKey("verifications.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("parent_revision_id", sa.String(36), sa.ForeignKey("document_revisions.id", ondelete="SET NULL")),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("source_kind", sa.String(30), nullable=False),
        sa.Column("content_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("workflow_revision_id", "version", name="uq_document_revision_version"),
        sa.UniqueConstraint("workflow_revision_id", "content_hash", name="uq_document_revision_hash"),
    )
    op.create_table(
        "document_evidence",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("document_revision_id", sa.String(36), sa.ForeignKey("document_revisions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("claim_path", sa.String(200), nullable=False),
        sa.Column("verification_id", sa.String(36), sa.ForeignKey("verifications.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("observation_id", sa.String(36), sa.ForeignKey("observations.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("screenshot_artifact_id", sa.String(36), sa.ForeignKey("artifacts.id", ondelete="RESTRICT"), nullable=False),
        sa.UniqueConstraint("document_revision_id", "claim_path", name="uq_document_evidence_claim"),
    )
    op.create_table(
        "review_decisions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("document_revision_id", sa.String(36), sa.ForeignKey("document_revisions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("decision", sa.String(20), nullable=False),
        sa.Column("reviewer", sa.String(200), nullable=False),
        sa.Column("notes", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "exports",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("project_id", sa.String(36), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("output_path", sa.Text(), nullable=False),
        sa.Column("document_revision_ids_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("exports")
    op.drop_table("review_decisions")
    op.drop_table("document_evidence")
    op.drop_table("document_revisions")
    op.drop_table("owner_sources")
