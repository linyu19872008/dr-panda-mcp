"""audit: add tool, elapsed_ms, error_code for queryable call analytics.

Revision ID: 0015_audit_tool_columns
Revises: 0014_target_operator_notes
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0015_audit_tool_columns"
down_revision = "0014_target_operator_notes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    columns = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("audit")}
    if "tool" not in columns:
        op.add_column("audit", sa.Column("tool", sa.String(64), nullable=True))
    if "elapsed_ms" not in columns:
        op.add_column("audit", sa.Column("elapsed_ms", sa.BigInteger(), nullable=True))
    if "error_code" not in columns:
        op.add_column("audit", sa.Column("error_code", sa.String(32), nullable=True))
    indexes = {index["name"] for index in sa.inspect(op.get_bind()).get_indexes("audit")}
    if "ix_audit_tool_created_at" not in indexes:
        op.create_index("ix_audit_tool_created_at", "audit", ["tool", "created_at"])


def downgrade() -> None:
    indexes = {index["name"] for index in sa.inspect(op.get_bind()).get_indexes("audit")}
    if "ix_audit_tool_created_at" in indexes:
        op.drop_index("ix_audit_tool_created_at", table_name="audit")
    columns = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("audit")}
    if "error_code" in columns:
        op.drop_column("audit", "error_code")
    if "elapsed_ms" in columns:
        op.drop_column("audit", "elapsed_ms")
    if "tool" in columns:
        op.drop_column("audit", "tool")
