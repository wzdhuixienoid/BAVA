"""Persist mock-provider definitive error facts.

Revision ID: 0010
Revises: 0009
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "mock_bank_transfers",
        sa.Column("error_code", sa.String(length=100), nullable=True),
    )
    op.add_column(
        "mock_bank_transfers",
        sa.Column("error_message", sa.String(length=500), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("mock_bank_transfers", "error_message")
    op.drop_column("mock_bank_transfers", "error_code")
