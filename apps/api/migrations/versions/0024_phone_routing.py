"""User-scoped Mock phone registrations and bounded lookup counters."""

import sqlalchemy as sa
from alembic import op

revision = "0024"
down_revision = "0023"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "phone_routes",
        sa.Column("user_id", sa.String(255), primary_key=True),
        sa.Column("phone_token", sa.String(64), primary_key=True),
        sa.Column("payee_id", sa.String(255), primary_key=True),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
    )
    op.create_table(
        "phone_lookup_limits",
        sa.Column("user_id", sa.String(255), primary_key=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("phone_lookup_limits")
    op.drop_table("phone_routes")
