"""Add transfer approvals and reauthentication challenges.

Revision ID: 0007
Revises: 0006
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

approval_type = postgresql.ENUM("TRANSFER", name="approval_type", create_type=False)
approval_status = postgresql.ENUM(
    "PENDING",
    "APPROVED",
    "INVALIDATED",
    "EXPIRED",
    name="approval_status",
    create_type=False,
)
reauth_method = postgresql.ENUM("MOCK_CODE", name="reauthentication_method", create_type=False)
reauth_status = postgresql.ENUM(
    "PENDING",
    "VERIFIED",
    "FAILED",
    "EXPIRED",
    "INVALIDATED",
    name="reauthentication_status",
    create_type=False,
)


def upgrade() -> None:
    op.execute("ALTER TYPE workflow_status ADD VALUE IF NOT EXISTS 'REAUTH_REQUIRED'")
    op.execute("ALTER TYPE workflow_status ADD VALUE IF NOT EXISTS 'READY_FOR_COMMIT'")
    op.execute("CREATE TYPE approval_type AS ENUM ('TRANSFER')")
    op.execute(
        "CREATE TYPE approval_status AS ENUM ('PENDING', 'APPROVED', 'INVALIDATED', 'EXPIRED')"
    )
    op.execute("CREATE TYPE reauthentication_method AS ENUM ('MOCK_CODE')")
    op.execute(
        "CREATE TYPE reauthentication_status AS ENUM "
        "('PENDING', 'VERIFIED', 'FAILED', 'EXPIRED', 'INVALIDATED')"
    )
    op.create_table(
        "approvals",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.String(length=255), nullable=False),
        sa.Column("workflow_id", sa.Uuid(), nullable=False),
        sa.Column("approval_type", approval_type, nullable=False),
        sa.Column("payload_json", sa.JSON(), nullable=False),
        sa.Column("payload_hash", sa.String(length=64), nullable=False),
        sa.Column("status", approval_status, nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("invalidated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["workflow_id"], ["workflows.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_approvals_user_id", "approvals", ["user_id"])
    op.create_index("ix_approvals_workflow_id", "approvals", ["workflow_id"])
    op.create_index("ix_approvals_payload_hash", "approvals", ["payload_hash"])
    op.create_index("ix_approvals_status", "approvals", ["status"])
    op.create_index("ix_approvals_workflow_created_at", "approvals", ["workflow_id", "created_at"])
    op.create_table(
        "reauthentications",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.String(length=255), nullable=False),
        sa.Column("workflow_id", sa.Uuid(), nullable=False),
        sa.Column("approval_id", sa.Uuid(), nullable=False),
        sa.Column("method", reauth_method, nullable=False),
        sa.Column("status", reauth_status, nullable=False),
        sa.Column("provider_reference", sa.String(length=255), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["workflow_id"], ["workflows.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["approval_id"], ["approvals.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_reauthentications_user_id", "reauthentications", ["user_id"])
    op.create_index("ix_reauthentications_workflow_id", "reauthentications", ["workflow_id"])
    op.create_index("ix_reauthentications_approval_id", "reauthentications", ["approval_id"])
    op.create_index("ix_reauthentications_status", "reauthentications", ["status"])
    op.create_index(
        "ix_reauth_workflow_created_at",
        "reauthentications",
        ["workflow_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_table("reauthentications")
    op.drop_table("approvals")
    op.execute("DROP TYPE reauthentication_status")
    op.execute("DROP TYPE reauthentication_method")
    op.execute("DROP TYPE approval_status")
    op.execute("DROP TYPE approval_type")
    # PostgreSQL workflow enum values intentionally remain.
