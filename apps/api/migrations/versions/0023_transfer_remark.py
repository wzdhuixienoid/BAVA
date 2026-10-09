"""Preserve the submitted transfer remark in the immutable Mock ledger."""

import sqlalchemy as sa
from alembic import op

revision = "0023"
down_revision = "0022"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "mock_bank_transfers",
        sa.Column("remark", sa.String(100), nullable=False, server_default=""),
    )


def downgrade() -> None:
    op.drop_column("mock_bank_transfers", "remark")
