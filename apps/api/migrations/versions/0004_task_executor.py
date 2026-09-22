"""Add authoritative task executor identity.

Revision ID: 0004
Revises: 0003
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

executor_type = sa.Enum("AGENT", name="executor_type")


def upgrade() -> None:
    executor_type.create(op.get_bind(), checkfirst=True)
    op.add_column(
        "tasks",
        sa.Column("executor_type", executor_type, nullable=True),
    )
    op.add_column(
        "tasks",
        sa.Column("executor_id", sa.String(length=255), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("tasks", "executor_id")
    op.drop_column("tasks", "executor_type")
    executor_type.drop(op.get_bind(), checkfirst=True)
