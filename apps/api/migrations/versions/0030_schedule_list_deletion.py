"""Hide cancelled schedule tasks without removing financial evidence."""

import sqlalchemy as sa
from alembic import op

revision = "0030"
down_revision = "0029"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "scheduled_transfers", sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True)
    )


def downgrade():
    op.drop_column("scheduled_transfers", "deleted_at")
