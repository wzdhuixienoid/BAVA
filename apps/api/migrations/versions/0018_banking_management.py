"""Conversation soft deletion, payees and reversible subscription management."""

import sqlalchemy as sa
from alembic import op

revision = "0018"
down_revision = "0017"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        with op.get_context().autocommit_block():
            for name in ("workflow_type", "approval_type", "operation_type"):
                op.execute(
                    sa.text(f"ALTER TYPE {name} ADD VALUE IF NOT EXISTS 'SUBSCRIPTION_RESUME'")
                )
    op.add_column(
        "conversations", sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.create_table(
        "payees",
        sa.Column("payee_id", sa.String(255), primary_key=True),
        sa.Column("user_id", sa.String(255), nullable=False),
        sa.Column("display_name", sa.String(100), nullable=False),
        sa.Column("bank_name", sa.String(100), nullable=False),
        sa.Column("account_suffix", sa.String(4), nullable=False),
        sa.Column("phone_alias", sa.String(100), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "user_id", "display_name", "bank_name", "account_suffix", name="uq_payee_identity"
        ),
    )
    op.create_index("ix_payees_user_id", "payees", ["user_id"])
    op.create_table(
        "mock_subscription_states",
        sa.Column("user_id", sa.String(255), primary_key=True),
        sa.Column("subscription_id", sa.String(255), primary_key=True),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("next_billing_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "mock_subscription_actions",
        sa.Column("provider_reference", sa.String(255), primary_key=True),
        sa.Column("user_id", sa.String(255), nullable=False),
        sa.Column("subscription_id", sa.String(255), nullable=False),
        sa.Column("idempotency_key", sa.Uuid(), nullable=False),
        sa.Column("action", sa.String(30), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("error_code", sa.String(100), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )
    for column in ("user_id", "subscription_id", "status"):
        op.create_index(
            f"ix_mock_subscription_actions_{column}", "mock_subscription_actions", [column]
        )
    op.create_index(
        "ix_mock_subscription_actions_idempotency_key",
        "mock_subscription_actions",
        ["idempotency_key"],
        unique=True,
    )
    # Legacy evidence stays intact. A state overlay replaces the old permanent cancelled set.
    op.execute(
        sa.text("""
        INSERT INTO mock_subscription_states
            (user_id, subscription_id, status, version, next_billing_at, updated_at)
        SELECT user_id, subscription_id, 'CANCELLED', 0, NULL,
               MAX(COALESCE(completed_at, created_at))
        FROM mock_subscription_cancellations WHERE status = 'SUCCEEDED'
        GROUP BY user_id, subscription_id
    """)
    )


def downgrade() -> None:
    connection = op.get_bind()
    for statement in (
        "SELECT count(*) FROM mock_subscription_actions",
        "SELECT count(*) FROM payees",
        "SELECT count(*) FROM conversations WHERE deleted_at IS NOT NULL",
        "SELECT count(*) FROM workflows WHERE workflow_type = 'SUBSCRIPTION_RESUME'",
    ):
        if connection.scalar(sa.text(statement)):
            raise RuntimeError("Preserve management records before downgrading to 0017")
    for table in ("mock_subscription_actions", "mock_subscription_states", "payees"):
        op.drop_table(table)
    op.drop_column("conversations", "deleted_at")
    # PostgreSQL enum additions are retained so existing evidence remains readable.
