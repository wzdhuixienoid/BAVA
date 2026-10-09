"""Durable Mock single-use appointment authority and leases."""

import sqlalchemy as sa
from alembic import op

revision = "0025"
down_revision = "0024"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "scheduled_transfers",
        sa.Column("schedule_id", sa.Uuid(), primary_key=True),
        sa.Column("user_id", sa.String(255), nullable=False),
        sa.Column(
            "workflow_id", sa.Uuid(), sa.ForeignKey("workflows.id"), nullable=False, unique=True
        ),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("scheduled_for", sa.DateTime(timezone=True)),
        sa.Column("execute_deadline", sa.DateTime(timezone=True)),
        sa.Column("business_timezone", sa.String(64), nullable=False),
        sa.Column("authorization_id", sa.Uuid()),
        sa.Column("operation_id", sa.Uuid(), sa.ForeignKey("operations.id"), unique=True),
        sa.Column("lease_owner", sa.String(255)),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True)),
        sa.Column("error_code", sa.String(100)),
    )
    op.create_index("ix_scheduled_transfers_user_id", "scheduled_transfers", ["user_id"])
    op.create_index(
        "ix_schedules_due", "scheduled_transfers", ["status", "scheduled_for", "lease_expires_at"]
    )
    op.create_table(
        "scheduled_authorizations",
        sa.Column("authorization_id", sa.Uuid(), primary_key=True),
        sa.Column(
            "schedule_id",
            sa.Uuid(),
            sa.ForeignKey("scheduled_transfers.schedule_id"),
            nullable=False,
        ),
        sa.Column("user_id", sa.String(255), nullable=False),
        sa.Column("workflow_id", sa.Uuid(), sa.ForeignKey("workflows.id"), nullable=False),
        sa.Column("approval_id", sa.Uuid(), sa.ForeignKey("approvals.id"), nullable=False),
        sa.Column("reauth_id", sa.Uuid(), sa.ForeignKey("reauthentications.id"), nullable=False),
        sa.Column("payload_hash", sa.String(64), nullable=False),
        sa.Column("payload_json", sa.JSON(), nullable=False),
        sa.Column("authorized_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.Column("used_at", sa.DateTime(timezone=True)),
    )
    op.create_index(
        "ix_scheduled_authorizations_schedule_id", "scheduled_authorizations", ["schedule_id"]
    )


def downgrade():
    op.drop_table("scheduled_authorizations")
    op.drop_table("scheduled_transfers")
