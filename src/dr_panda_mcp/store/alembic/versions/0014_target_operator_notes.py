"""targets.operator_notes: operator-provided AI troubleshooting hints.

Revision ID: 0014_target_operator_notes
Revises: 0013_capacity_settings
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0014_target_operator_notes"
down_revision = "0013_capacity_settings"
branch_labels = None
depends_on = None


def upgrade() -> None:
    columns = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("targets")}
    if "operator_notes" not in columns:
        op.add_column(
            "targets",
            sa.Column("operator_notes", sa.Text(), nullable=False, server_default=""),
        )


def downgrade() -> None:
    with op.batch_alter_table("targets") as batch:
        batch.drop_column("operator_notes")
