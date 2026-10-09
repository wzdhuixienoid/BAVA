"""Renewal reminders and durable observation of posted subscription charges."""

import sqlalchemy as sa
from alembic import op

revision = "0032"
down_revision = "0031"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "notifications",
        sa.Column("kind", sa.String(40), nullable=False, server_default="SCHEDULE_RESULT"),
    )
    op.create_table(
        "subscription_notification_cursors",
        sa.Column("user_id", sa.String(255), primary_key=True),
        sa.Column("seen_transaction_ids", sa.JSON(), nullable=False),
        sa.Column("last_billing_scan_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        "mock_subscription_charges",
        sa.Column("charge_id", sa.Uuid(), primary_key=True),
        sa.Column("user_id", sa.String(255), nullable=False),
        sa.Column("subscription_id", sa.String(255), nullable=False),
        sa.Column("source_account_id", sa.String(255), nullable=True),
        sa.Column("merchant", sa.String(100), nullable=False),
        sa.Column("amount", sa.Numeric(18, 2), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("billing_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("error_code", sa.String(100), nullable=True),
        sa.UniqueConstraint(
            "user_id", "subscription_id", "billing_at", name="uq_subscription_billing"
        ),
    )
    op.create_index(
        "ix_mock_subscription_charges_user_id", "mock_subscription_charges", ["user_id"]
    )


def downgrade():
    op.drop_table("mock_subscription_charges")
    op.drop_table("subscription_notification_cursors")
    op.drop_column("notifications", "kind")
