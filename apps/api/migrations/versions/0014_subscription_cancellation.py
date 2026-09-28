"""Add subscription cancellation operation facts and stable transfer risk date.

Revision ID: 0014
Revises: 0013
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0014"
down_revision: str | None = "0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TYPE workflow_type ADD VALUE IF NOT EXISTS 'SUBSCRIPTION_CANCEL'")
    op.execute("ALTER TYPE approval_type ADD VALUE IF NOT EXISTS 'SUBSCRIPTION_CANCEL'")
    op.execute("ALTER TYPE operation_type ADD VALUE IF NOT EXISTS 'SUBSCRIPTION_CANCEL'")
    op.add_column("operations", sa.Column("risk_business_date", sa.Date(), nullable=True))
    op.execute(
        "UPDATE operations SET risk_business_date = "
        "CAST(created_at AT TIME ZONE 'Asia/Shanghai' AS DATE) "
        "WHERE operation_type = 'TRANSFER'"
    )
    op.create_index("ix_operations_risk_business_date", "operations", ["risk_business_date"])
    op.create_table(
        "mock_subscription_cancellations",
        sa.Column("provider_reference", sa.String(length=255), nullable=False),
        sa.Column("user_id", sa.String(length=255), nullable=False),
        sa.Column("subscription_id", sa.String(length=255), nullable=False),
        sa.Column("idempotency_key", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("error_code", sa.String(length=100), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("provider_reference"),
        sa.UniqueConstraint("idempotency_key"),
    )
    op.create_index(
        "ix_mock_subscription_cancellations_user_id",
        "mock_subscription_cancellations",
        ["user_id"],
    )
    op.create_index(
        "ix_mock_subscription_cancellations_subscription_id",
        "mock_subscription_cancellations",
        ["subscription_id"],
    )
    op.create_index(
        "ix_mock_subscription_cancellations_status",
        "mock_subscription_cancellations",
        ["status"],
    )


def downgrade() -> None:
    op.drop_table("mock_subscription_cancellations")
    op.drop_index("ix_operations_risk_business_date", table_name="operations")
    op.drop_column("operations", "risk_business_date")
