"""Add transfer workflow persistence and workflow task routing.

Revision ID: 0006
Revises: 0005
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

workflow_type = postgresql.ENUM("TRANSFER", name="workflow_type", create_type=False)
workflow_status = postgresql.ENUM(
    "DRAFT",
    "WAITING_FOR_INPUT",
    "VALIDATING",
    "READY_FOR_REVIEW",
    "FAILED",
    "CANCELLED",
    name="workflow_status",
    create_type=False,
)


def upgrade() -> None:
    op.execute("ALTER TYPE executor_type ADD VALUE IF NOT EXISTS 'WORKFLOW'")
    op.execute("ALTER TYPE requested_output ADD VALUE IF NOT EXISTS 'WORKFLOW'")
    op.execute("CREATE TYPE workflow_type AS ENUM ('TRANSFER')")
    op.execute(
        "CREATE TYPE workflow_status AS ENUM "
        "('DRAFT', 'WAITING_FOR_INPUT', 'VALIDATING', 'READY_FOR_REVIEW', "
        "'FAILED', 'CANCELLED')"
    )
    op.create_table(
        "workflows",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.String(length=255), nullable=False),
        sa.Column("conversation_id", sa.Uuid(), nullable=False),
        sa.Column("source_task_id", sa.Uuid(), nullable=False),
        sa.Column("workflow_type", workflow_type, nullable=False),
        sa.Column("status", workflow_status, nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("state_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["conversation_id"], ["conversations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["source_task_id"], ["tasks.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("source_task_id"),
    )
    op.create_index("ix_workflows_user_id", "workflows", ["user_id"])
    op.create_index("ix_workflows_conversation_id", "workflows", ["conversation_id"])
    op.create_index("ix_workflows_source_task_id", "workflows", ["source_task_id"])
    op.create_index("ix_workflows_status", "workflows", ["status"])
    op.create_index("ix_workflows_user_created_at", "workflows", ["user_id", "created_at"])
    op.create_index(
        "ix_workflows_conversation_created_at", "workflows", ["conversation_id", "created_at"]
    )


def downgrade() -> None:
    op.drop_table("workflows")
    workflow_status.drop(op.get_bind(), checkfirst=True)
    workflow_type.drop(op.get_bind(), checkfirst=True)
    # PostgreSQL enum values intentionally remain; removing values is destructive.
