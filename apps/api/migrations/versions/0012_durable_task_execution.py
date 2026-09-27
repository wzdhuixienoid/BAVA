"""Add durable Task execution scheduling and lease metadata.

Revision ID: 0012
Revises: 0011
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0012"
down_revision: str | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("tasks", sa.Column("next_run_at", sa.DateTime(timezone=True)))
    op.add_column(
        "tasks",
        sa.Column(
            "execution_attempts",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
    )
    op.add_column("tasks", sa.Column("last_attempt_at", sa.DateTime(timezone=True)))
    op.add_column("tasks", sa.Column("lease_owner", sa.String(length=255)))
    op.add_column("tasks", sa.Column("lease_expires_at", sa.DateTime(timezone=True)))
    op.create_check_constraint(
        "ck_tasks_execution_attempts_nonnegative",
        "tasks",
        "execution_attempts >= 0",
    )

    # Only states that were already executable or explicitly crash-interrupted are
    # scheduled. Waiting and terminal Tasks remain unscheduled.
    op.execute(
        """
        UPDATE tasks
        SET next_run_at = CURRENT_TIMESTAMP,
            lease_owner = NULL,
            lease_expires_at = NULL
        WHERE status IN ('PENDING', 'RUNNING')
        """
    )
    op.execute(
        """
        UPDATE tasks
        SET next_run_at = CURRENT_TIMESTAMP,
            lease_owner = NULL,
            lease_expires_at = NULL
        WHERE status = 'INTERRUPTED'
          AND COALESCE((error_json ->> 'retryable')::boolean, false)
        """
    )
    op.create_index(
        "ix_tasks_execution_due",
        "tasks",
        ["status", "next_run_at", "lease_expires_at"],
        postgresql_where=sa.text("status IN ('PENDING', 'RUNNING', 'INTERRUPTED')"),
    )


def downgrade() -> None:
    op.drop_index("ix_tasks_execution_due", table_name="tasks")
    op.drop_constraint(
        "ck_tasks_execution_attempts_nonnegative", "tasks", type_="check"
    )
    op.drop_column("tasks", "lease_expires_at")
    op.drop_column("tasks", "lease_owner")
    op.drop_column("tasks", "last_attempt_at")
    op.drop_column("tasks", "execution_attempts")
    op.drop_column("tasks", "next_run_at")
