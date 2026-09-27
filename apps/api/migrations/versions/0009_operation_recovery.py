"""Add durable operation recovery scheduling and leases.

Revision ID: 0009
Revises: 0008
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "operations",
        sa.Column("next_reconcile_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "operations",
        sa.Column(
            "reconcile_attempts",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
    )
    op.add_column(
        "operations",
        sa.Column("last_reconcile_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "operations", sa.Column("lease_owner", sa.String(length=255), nullable=True)
    )
    op.add_column(
        "operations",
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_check_constraint(
        "ck_operations_reconcile_attempts_nonnegative",
        "operations",
        "reconcile_attempts >= 0",
    )
    op.execute(
        "UPDATE operations SET next_reconcile_at = CURRENT_TIMESTAMP "
        "WHERE status IN ('CREATED', 'SUBMITTED', 'UNKNOWN')"
    )
    op.create_index(
        "ix_operations_recovery_due",
        "operations",
        ["status", "next_reconcile_at", "lease_expires_at"],
        unique=False,
        postgresql_where=sa.text("status IN ('CREATED', 'SUBMITTED', 'UNKNOWN')"),
    )


def downgrade() -> None:
    op.drop_index("ix_operations_recovery_due", table_name="operations")
    op.drop_constraint(
        "ck_operations_reconcile_attempts_nonnegative", "operations", type_="check"
    )
    op.drop_column("operations", "lease_expires_at")
    op.drop_column("operations", "lease_owner")
    op.drop_column("operations", "last_reconcile_at")
    op.drop_column("operations", "reconcile_attempts")
    op.drop_column("operations", "next_reconcile_at")
