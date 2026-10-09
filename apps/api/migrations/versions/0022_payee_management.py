"""Persist user-scoped edits and soft deletion of existing and fixture payees."""

import sqlalchemy as sa
from alembic import op

revision = "0022"
down_revision = "0021"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("payees", sa.Column("source_payee_id", sa.String(255), nullable=True))
    op.add_column("payees", sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True))
    op.create_unique_constraint("uq_payee_source", "payees", ["user_id", "source_payee_id"])


def downgrade() -> None:
    if op.get_bind().scalar(
        sa.text(
            "SELECT count(*) FROM payees "
            "WHERE source_payee_id IS NOT NULL OR deleted_at IS NOT NULL"
        )
    ):
        raise RuntimeError("Preserve edited and deleted payees before downgrading to 0021")
    op.drop_constraint("uq_payee_source", "payees", type_="unique")
    op.drop_column("payees", "deleted_at")
    op.drop_column("payees", "source_payee_id")
