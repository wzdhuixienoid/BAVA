"""Retain the evidence behind transaction anomaly notifications."""

import sqlalchemy as sa
from alembic import op

revision = "0036"
down_revision = "0035"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("notifications", sa.Column("anomaly_snapshot", sa.JSON(), nullable=True))


def downgrade():
    if op.get_bind().scalar(
        sa.text(
            "SELECT count(*) FROM notifications "
            "WHERE kind = 'TRANSACTION_ANOMALY' AND anomaly_snapshot IS NOT NULL"
        )
    ):
        raise RuntimeError("Refusing destructive downgrade with anomaly notification evidence")
    op.drop_column("notifications", "anomaly_snapshot")
