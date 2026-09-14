"""Add Phase 2 discovery state graph and frontier tables."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002_phase2"
down_revision: str | None = "0001_phase1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("runs", sa.Column("stage", sa.String(40), nullable=False, server_default="capture"))
    op.add_column("runs", sa.Column("scenario", sa.String(100), nullable=False, server_default="default"))
    op.add_column("runs", sa.Column("discovery_mode", sa.String(30)))
    op.add_column("runs", sa.Column("limits_json", sa.Text()))

    op.create_table(
        "states",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("project_id", sa.String(36), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("role_id", sa.String(36), sa.ForeignKey("roles.id", ondelete="CASCADE"), nullable=False),
        sa.Column("scenario", sa.String(100), nullable=False),
        sa.Column("fingerprint", sa.String(64), nullable=False),
        sa.Column("algorithm_version", sa.String(40), nullable=False),
        sa.Column("route", sa.Text(), nullable=False),
        sa.Column("normalized_structure", sa.Text(), nullable=False),
        sa.Column(
            "representative_observation_id",
            sa.String(36),
            sa.ForeignKey("observations.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "project_id",
            "role_id",
            "scenario",
            "fingerprint",
            "algorithm_version",
            name="uq_state_identity",
        ),
    )
    with op.batch_alter_table("observations") as batch_op:
        batch_op.add_column(
            sa.Column(
                "state_id",
                sa.String(36),
                sa.ForeignKey("states.id", name="fk_observations_state_id", ondelete="SET NULL"),
            )
        )
    op.create_table(
        "transitions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("run_id", sa.String(36), sa.ForeignKey("runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("source_state_id", sa.String(36), sa.ForeignKey("states.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("target_state_id", sa.String(36), sa.ForeignKey("states.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("attempt_id", sa.String(36), sa.ForeignKey("action_attempts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("run_id", "attempt_id", name="uq_transition_attempt"),
    )
    op.create_table(
        "frontier_items",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("run_id", sa.String(36), sa.ForeignKey("runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("state_id", sa.String(36), sa.ForeignKey("states.id", ondelete="CASCADE"), nullable=False),
        sa.Column("action_signature", sa.String(64), nullable=False),
        sa.Column("action_json", sa.Text(), nullable=False),
        sa.Column("path_json", sa.Text(), nullable=False),
        sa.Column("label", sa.String(300), nullable=False),
        sa.Column("rationale", sa.Text(), nullable=False),
        sa.Column("priority", sa.Integer(), nullable=False),
        sa.Column("depth", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("reason", sa.Text()),
        sa.Column("attempt_id", sa.String(36), sa.ForeignKey("action_attempts.id", ondelete="SET NULL")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("run_id", "state_id", "action_signature", name="uq_frontier_candidate"),
    )
    op.create_table(
        "features",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("run_id", sa.String(36), sa.ForeignKey("runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("role_id", sa.String(36), sa.ForeignKey("roles.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("state_id", sa.String(36), sa.ForeignKey("states.id", ondelete="RESTRICT"), nullable=False),
        sa.Column(
            "observation_id",
            sa.String(36),
            sa.ForeignKey("observations.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("unresolved_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("run_id", "title", name="uq_feature_run_title"),
    )
    op.create_table(
        "usage_events",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("run_id", sa.String(36), sa.ForeignKey("runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("model_name", sa.String(200), nullable=False),
        sa.Column("input_tokens", sa.Integer(), nullable=False),
        sa.Column("output_tokens", sa.Integer(), nullable=False),
        sa.Column("usage_reported", sa.Integer(), nullable=False),
        sa.Column("duration_ms", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("usage_events")
    op.drop_table("features")
    op.drop_table("frontier_items")
    op.drop_table("transitions")
    with op.batch_alter_table("observations") as batch_op:
        batch_op.drop_column("state_id")
    op.drop_table("states")
    op.drop_column("runs", "limits_json")
    op.drop_column("runs", "discovery_mode")
    op.drop_column("runs", "scenario")
    op.drop_column("runs", "stage")
