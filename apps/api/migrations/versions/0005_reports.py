"""Add requested output and immutable reports.

Revision ID: 0005
Revises: 0004
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

requested_output = sa.Enum("ANSWER", "MONTHLY_REPORT", name="requested_output")
report_type = sa.Enum("MONTHLY_SPENDING", name="report_type")


def upgrade() -> None:
    requested_output.create(op.get_bind(), checkfirst=True)
    op.add_column(
        "tasks",
        sa.Column("requested_output", requested_output, nullable=True),
    )
    op.create_table(
        "reports",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.String(length=255), nullable=False),
        sa.Column("conversation_id", sa.Uuid(), nullable=False),
        sa.Column("source_task_id", sa.Uuid(), nullable=False),
        sa.Column("report_type", report_type, nullable=False),
        sa.Column("report_version", sa.Integer(), nullable=False),
        sa.Column("skill_id", sa.String(length=255), nullable=False),
        sa.Column("skill_version", sa.Integer(), nullable=False),
        sa.Column("period", sa.String(length=7), nullable=False),
        sa.Column("content_json", sa.JSON(), nullable=False),
        sa.Column("source_snapshot_hash", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["conversation_id"], ["conversations.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["source_task_id"], ["tasks.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "source_task_id",
            "report_type",
            "report_version",
            name="uq_reports_source_task_type_version",
        ),
    )
    op.create_index("ix_reports_user_id", "reports", ["user_id"])
    op.create_index("ix_reports_conversation_id", "reports", ["conversation_id"])
    op.create_index("ix_reports_source_task_id", "reports", ["source_task_id"])
    op.create_index("ix_reports_period", "reports", ["period"])
    op.create_index("ix_reports_created_at", "reports", ["created_at"])
    op.create_index(
        "ix_reports_user_created_at", "reports", ["user_id", "created_at"]
    )
    op.create_index(
        "ix_reports_conversation_created_at",
        "reports",
        ["conversation_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_table("reports")
    op.drop_column("tasks", "requested_output")
    report_type.drop(op.get_bind(), checkfirst=True)
    requested_output.drop(op.get_bind(), checkfirst=True)
