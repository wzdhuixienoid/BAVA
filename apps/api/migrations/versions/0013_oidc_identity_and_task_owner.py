"""Add OIDC identity mappings and durable Task ownership.

Revision ID: 0013
Revises: 0012
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0013"
down_revision: str | None = "0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "identity_mappings",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.String(length=255), nullable=False),
        sa.Column("issuer", sa.String(length=2048), nullable=False),
        sa.Column("subject", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("issuer", "subject", name="uq_identity_mappings_issuer_subject"),
    )
    op.create_index("ix_identity_mappings_user_id", "identity_mappings", ["user_id"])

    op.add_column("tasks", sa.Column("user_id", sa.String(length=255)))
    op.execute(
        """
        UPDATE tasks
        SET user_id = conversations.user_id
        FROM conversations
        WHERE tasks.conversation_id = conversations.id
        """
    )
    op.alter_column("tasks", "user_id", nullable=False)
    op.create_index("ix_tasks_user_id", "tasks", ["user_id"])

    op.add_column("mock_bank_transfers", sa.Column("user_id", sa.String(length=255)))
    op.execute(
        """
        UPDATE mock_bank_transfers
        SET user_id = operations.user_id
        FROM operations
        WHERE mock_bank_transfers.idempotency_key = operations.idempotency_key
        """
    )
    op.alter_column("mock_bank_transfers", "user_id", nullable=False)
    op.create_index("ix_mock_bank_transfers_user_id", "mock_bank_transfers", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_mock_bank_transfers_user_id", table_name="mock_bank_transfers")
    op.drop_column("mock_bank_transfers", "user_id")
    op.drop_index("ix_tasks_user_id", table_name="tasks")
    op.drop_column("tasks", "user_id")
    op.drop_index("ix_identity_mappings_user_id", table_name="identity_mappings")
    op.drop_table("identity_mappings")
