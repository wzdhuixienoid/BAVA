"""Finite Mock recurring authority and unique occurrence membership."""

import sqlalchemy as sa
from alembic import op

revision = "0029"
down_revision = "0028"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "recurring_transfers",
        sa.Column("series_id", sa.Uuid(), primary_key=True),
        sa.Column("user_id", sa.String(255), nullable=False),
        sa.Column(
            "root_workflow_id",
            sa.Uuid(),
            sa.ForeignKey("workflows.id"),
            nullable=False,
            unique=True,
        ),
        sa.Column("approval_id", sa.Uuid(), sa.ForeignKey("approvals.id"), nullable=False),
        sa.Column("reauth_id", sa.Uuid(), sa.ForeignKey("reauthentications.id"), nullable=False),
        sa.Column("scope_json", sa.JSON(), nullable=False),
        sa.Column("scope_hash", sa.String(64), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.Column("authorized_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_recurring_transfers_user_id", "recurring_transfers", ["user_id"])
    op.add_column(
        "scheduled_transfers",
        sa.Column("series_id", sa.Uuid(), sa.ForeignKey("recurring_transfers.series_id")),
    )
    op.add_column("scheduled_transfers", sa.Column("occurrence_index", sa.Integer()))
    op.create_index("ix_scheduled_transfers_series_id", "scheduled_transfers", ["series_id"])
    op.create_unique_constraint(
        "uq_recurring_occurrence", "scheduled_transfers", ["series_id", "occurrence_index"]
    )


def downgrade():
    op.drop_constraint("uq_recurring_occurrence", "scheduled_transfers", type_="unique")
    op.drop_index("ix_scheduled_transfers_series_id", "scheduled_transfers")
    op.drop_column("scheduled_transfers", "occurrence_index")
    op.drop_column("scheduled_transfers", "series_id")
    op.drop_table("recurring_transfers")
