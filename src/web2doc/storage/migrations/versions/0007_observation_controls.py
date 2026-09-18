"""Persist structured controls for offline documentation planning."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007_observation_controls"
down_revision: str | None = "0006_feature_references"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "observations",
        sa.Column("controls_json", sa.Text(), nullable=False, server_default="[]"),
    )


def downgrade() -> None:
    op.drop_column("observations", "controls_json")
