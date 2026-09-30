"""Persistent constrained Plan DAG (Task remains the execution authority)."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0016"
down_revision: str | None = "0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "plans",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("user_id", sa.String(255), nullable=False),
        sa.Column(
            "conversation_id",
            sa.Uuid(),
            sa.ForeignKey("conversations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "source_task_id",
            sa.Uuid(),
            sa.ForeignKey("tasks.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column("goal_summary", sa.String(500), nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("manual_takeover", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_plans_user_created_at", "plans", ["user_id", "created_at"])
    op.create_index("ix_plans_conversation_created_at", "plans", ["conversation_id", "created_at"])
    op.create_table(
        "plan_steps",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "plan_id", sa.Uuid(), sa.ForeignKey("plans.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("step_key", sa.String(64), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("display_title", sa.String(160), nullable=False),
        sa.Column("capability", sa.String(40), nullable=False),
        sa.Column("executor_kind", sa.String(20), nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("subtask_query", sa.String(500)),
        sa.Column("output_json", sa.JSON()),
        sa.Column("linked_workflow_id", sa.Uuid(), sa.ForeignKey("workflows.id")),
        sa.Column("error_code", sa.String(100)),
        sa.Column("error_message", sa.String(500)),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("plan_id", "step_key", name="uq_plan_steps_key"),
        sa.UniqueConstraint("plan_id", "ordinal", name="uq_plan_steps_ordinal"),
    )
    op.create_index("ix_plan_steps_plan_status", "plan_steps", ["plan_id", "status"])
    op.create_index("ix_plan_steps_linked_workflow", "plan_steps", ["linked_workflow_id"])
    op.create_table(
        "plan_step_dependencies",
        sa.Column(
            "step_id",
            sa.Uuid(),
            sa.ForeignKey("plan_steps.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "depends_on_step_id",
            sa.Uuid(),
            sa.ForeignKey("plan_steps.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.CheckConstraint("step_id <> depends_on_step_id", name="ck_plan_no_self"),
    )


def downgrade() -> None:
    op.drop_table("plan_step_dependencies")
    op.drop_table("plan_steps")
    op.drop_table("plans")
