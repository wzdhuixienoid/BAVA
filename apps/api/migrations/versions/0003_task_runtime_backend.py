"""Add interrupted tasks and frozen runtime backend.

Revision ID: 0003
Revises: 0002
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

runtime_backend = sa.Enum("MANUAL", "LANGGRAPH", name="runtime_backend")


def upgrade() -> None:
    op.execute("ALTER TYPE task_status ADD VALUE IF NOT EXISTS 'INTERRUPTED'")
    runtime_backend.create(op.get_bind(), checkfirst=True)
    op.add_column(
        "tasks",
        sa.Column(
            "runtime_backend",
            runtime_backend,
            nullable=False,
            server_default="MANUAL",
        ),
    )
    op.alter_column("tasks", "runtime_backend", server_default=None)


def downgrade() -> None:
    op.drop_column("tasks", "runtime_backend")
    runtime_backend.drop(op.get_bind(), checkfirst=True)
    # PostgreSQL enum values are intentionally not destructively rewritten on downgrade.
