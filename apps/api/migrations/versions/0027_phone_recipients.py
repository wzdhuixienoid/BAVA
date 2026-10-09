"""Saved phone recipients, independent of authoritative bank routing."""

import sqlalchemy as sa
from alembic import op

revision = "0027"
down_revision = "0026"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "phone_recipients",
        sa.Column("recipient_id", sa.Uuid(), primary_key=True),
        sa.Column("user_id", sa.String(255), nullable=False),
        sa.Column("phone_token", sa.String(64), nullable=False),
        sa.Column("masked_phone", sa.String(32), nullable=False),
        sa.Column("payee_id", sa.String(255), nullable=False),
        sa.Column("alias", sa.String(100), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("user_id", "phone_token", "payee_id", name="uq_phone_recipient"),
    )
    op.create_index("ix_phone_recipients_user_id", "phone_recipients", ["user_id"])


def downgrade():
    op.drop_table("phone_recipients")
