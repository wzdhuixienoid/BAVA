"""Add persistent Security Guard state.

Revision ID: 0015
Revises: 0014
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0015"
down_revision: str | None = "0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "security_guard_states",
        sa.Column("user_id", sa.String(length=255), nullable=False),
        sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("lock_reason", sa.String(length=50), nullable=True),
        sa.Column("reauth_failure_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("reauth_window_started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("bypass_attempt_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("bypass_window_started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("user_id"),
    )


def downgrade() -> None:
    op.drop_table("security_guard_states")
