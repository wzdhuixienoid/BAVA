"""Owner-scoped payment exemption capped at 200 CNY; the daily cap remains independent."""

import sqlalchemy as sa
from alembic import op

revision = "0038"
down_revision = "0037"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "transfer_security_preferences",
        sa.Column("user_id", sa.String(255), primary_key=True),
        sa.Column("passwordless_limit", sa.Numeric(5, 2), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "passwordless_limit >= 0 AND passwordless_limit <= 200",
            name="ck_transfer_passwordless_limit_range",
        ),
    )


def downgrade():
    if op.get_bind().scalar(sa.text("SELECT count(*) FROM transfer_security_preferences")):
        raise RuntimeError("Refusing downgrade with personal payment security preferences")
    op.drop_table("transfer_security_preferences")
