"""Add transfer operations and persistent mock-provider ledger.

Revision ID: 0008
Revises: 0007
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

operation_type = postgresql.ENUM("TRANSFER", name="operation_type", create_type=False)
operation_status = postgresql.ENUM(
    "CREATED",
    "SUBMITTED",
    "UNKNOWN",
    "SUCCEEDED",
    "FAILED",
    name="operation_status",
    create_type=False,
)


def upgrade() -> None:
    op.execute("ALTER TYPE workflow_status ADD VALUE IF NOT EXISTS 'COMMITTING'")
    op.execute("ALTER TYPE workflow_status ADD VALUE IF NOT EXISTS 'SUCCEEDED'")
    op.execute("ALTER TYPE approval_status ADD VALUE IF NOT EXISTS 'CONSUMED'")
    op.execute("CREATE TYPE operation_type AS ENUM ('TRANSFER')")
    op.execute(
        "CREATE TYPE operation_status AS ENUM "
        "('CREATED', 'SUBMITTED', 'UNKNOWN', 'SUCCEEDED', 'FAILED')"
    )
    op.create_table(
        "operations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.String(length=255), nullable=False),
        sa.Column("workflow_id", sa.Uuid(), nullable=False),
        sa.Column("approval_id", sa.Uuid(), nullable=False),
        sa.Column("operation_type", operation_type, nullable=False),
        sa.Column("payload_json", sa.JSON(), nullable=False),
        sa.Column("payload_hash", sa.String(length=64), nullable=False),
        sa.Column("idempotency_key", sa.Uuid(), nullable=False),
        sa.Column("status", operation_status, nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("provider_reference", sa.String(length=255), nullable=True),
        sa.Column("error_code", sa.String(length=100), nullable=True),
        sa.Column("error_message", sa.String(length=500), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["workflow_id"], ["workflows.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["approval_id"], ["approvals.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("approval_id"),
        sa.UniqueConstraint("idempotency_key"),
        sa.UniqueConstraint(
            "workflow_id", "operation_type", name="uq_operations_workflow_type"
        ),
    )
    op.create_index("ix_operations_user_id", "operations", ["user_id"])
    op.create_index("ix_operations_workflow_id", "operations", ["workflow_id"])
    op.create_index("ix_operations_approval_id", "operations", ["approval_id"])
    op.create_index("ix_operations_idempotency_key", "operations", ["idempotency_key"])
    op.create_index("ix_operations_status", "operations", ["status"])
    op.create_index(
        "ix_operations_user_created_at", "operations", ["user_id", "created_at"]
    )
    op.add_column("approvals", sa.Column("consumed_by_operation_id", sa.Uuid(), nullable=True))
    op.create_unique_constraint(
        "uq_approvals_consumed_by_operation_id",
        "approvals",
        ["consumed_by_operation_id"],
    )
    op.create_foreign_key(
        "fk_approvals_consumed_operation",
        "approvals",
        "operations",
        ["consumed_by_operation_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_table(
        "mock_bank_transfers",
        sa.Column("provider_reference", sa.String(length=255), nullable=False),
        sa.Column("idempotency_key", sa.Uuid(), nullable=False),
        sa.Column("source_account_id", sa.String(length=255), nullable=False),
        sa.Column("payee_id", sa.String(length=255), nullable=False),
        sa.Column("amount", sa.Numeric(18, 2), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("applied_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("provider_reference"),
        sa.UniqueConstraint("idempotency_key"),
    )
    op.create_index(
        "ix_mock_bank_transfers_idempotency_key",
        "mock_bank_transfers",
        ["idempotency_key"],
    )
    op.create_index(
        "ix_mock_bank_transfers_source_account_id",
        "mock_bank_transfers",
        ["source_account_id"],
    )
    op.create_index("ix_mock_bank_transfers_status", "mock_bank_transfers", ["status"])


def downgrade() -> None:
    op.drop_table("mock_bank_transfers")
    op.drop_constraint("fk_approvals_consumed_operation", "approvals", type_="foreignkey")
    op.drop_constraint(
        "uq_approvals_consumed_by_operation_id", "approvals", type_="unique"
    )
    op.drop_column("approvals", "consumed_by_operation_id")
    op.drop_table("operations")
    op.execute("DROP TYPE operation_status")
    op.execute("DROP TYPE operation_type")
    # PostgreSQL enum values intentionally remain.
