"""Credential encryption, explicit subscription consent and independent action audit."""

import sqlalchemy as sa
from alembic import op

revision = "0037"
down_revision = "0036"
branch_labels = None
depends_on = None


def upgrade():
    if op.get_bind().dialect.name == "postgresql":
        with op.get_context().autocommit_block():
            op.execute("ALTER TYPE reauthentication_method ADD VALUE IF NOT EXISTS 'TOTP'")
    op.create_table(
        "domain_action_audits",
        sa.Column("trace_id", sa.Uuid(), primary_key=True),
        sa.Column("user_id", sa.String(255), nullable=False),
        sa.Column("action", sa.String(100), nullable=False),
        sa.Column("resource_id", sa.String(255), nullable=False),
        sa.Column("idempotency_key", sa.Uuid(), nullable=True),
        sa.Column("payload_hash", sa.String(64), nullable=False),
        sa.Column("outcome", sa.String(50), nullable=False),
        sa.Column("evidence", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_domain_action_audits_user_id", "domain_action_audits", ["user_id"])
    op.create_table(
        "totp_credentials",
        sa.Column("user_id", sa.String(255), primary_key=True),
        sa.Column("secret_ciphertext", sa.Text(), nullable=True),
        sa.Column("pending_ciphertext", sa.Text(), nullable=True),
        sa.Column("pending_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_counter", sa.Integer(), nullable=False),
        sa.Column("failure_count", sa.Integer(), nullable=False),
        sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_table(
        "subscription_read_consents",
        sa.Column("user_id", sa.String(255), primary_key=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade():
    for table in ("domain_action_audits", "totp_credentials"):
        if op.get_bind().scalar(sa.text(f"SELECT count(*) FROM {table}")):
            raise RuntimeError("Refusing downgrade with retained security evidence or credentials")
    op.drop_table("subscription_read_consents")
    op.drop_index("ix_domain_action_audits_user_id", table_name="domain_action_audits")
    op.drop_table("domain_action_audits")
    op.drop_table("totp_credentials")
    # PostgreSQL enum labels remain to preserve any historical challenge evidence.
