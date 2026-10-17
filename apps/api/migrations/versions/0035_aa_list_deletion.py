"""Hide fully cancelled AA collections from the initiator's list, retaining evidence."""

import sqlalchemy as sa
from alembic import op

revision = "0035"
down_revision = "0034"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("aa_requests", sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True))


def downgrade():
    op.drop_column("aa_requests", "deleted_at")
