"""Extend persisted Plan steps with constrained conditions."""

import sqlalchemy as sa
from alembic import op

revision = "0017"
down_revision = "0016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "plan_steps",
        sa.Column("step_kind", sa.String(20), nullable=False, server_default="CAPABILITY"),
    )
    op.add_column("plan_steps", sa.Column("condition_spec_json", sa.JSON(), nullable=True))
    op.add_column("plan_steps", sa.Column("condition_decision_json", sa.JSON(), nullable=True))
    op.add_column("plan_steps", sa.Column("guard_condition_step_id", sa.Uuid(), nullable=True))
    op.alter_column("plan_steps", "capability", existing_type=sa.String(40), nullable=True)
    op.create_foreign_key(
        "fk_plan_steps_guard_condition",
        "plan_steps",
        "plan_steps",
        ["guard_condition_step_id"],
        ["id"],
    )
    op.create_index(
        "ix_plan_steps_guard_condition_step_id", "plan_steps", ["guard_condition_step_id"]
    )


def downgrade() -> None:
    # Remove condition plans explicitly before downgrade; preserve capability semantics.
    connection = op.get_bind()
    if connection.scalar(sa.text("SELECT count(*) FROM plan_steps WHERE step_kind = 'CONDITION'")):
        raise RuntimeError("Remove condition plans before downgrading to 0016")
    op.drop_index("ix_plan_steps_guard_condition_step_id", table_name="plan_steps")
    op.drop_constraint("fk_plan_steps_guard_condition", "plan_steps", type_="foreignkey")
    op.alter_column("plan_steps", "capability", existing_type=sa.String(40), nullable=False)
    for name in (
        "guard_condition_step_id",
        "condition_decision_json",
        "condition_spec_json",
        "step_kind",
    ):
        op.drop_column("plan_steps", name)
