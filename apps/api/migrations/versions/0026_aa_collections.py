"""Immutable AA publication, one Operation per share, acknowledged Mock credits."""

import sqlalchemy as sa
from alembic import op

revision = "0026"
down_revision = "0025"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "aa_requests",
        sa.Column("request_id", sa.Uuid(), primary_key=True),
        sa.Column("user_id", sa.String(255), nullable=False),
        sa.Column("conversation_id", sa.Uuid(), sa.ForeignKey("conversations.id"), nullable=False),
        sa.Column(
            "source_task_id", sa.Uuid(), sa.ForeignKey("tasks.id"), nullable=False, unique=True
        ),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("draft_json", sa.JSON(), nullable=False),
        sa.Column("snapshot_json", sa.JSON()),
        sa.Column("payload_hash", sa.String(64)),
        sa.Column("deadline", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_aa_requests_user_id", "aa_requests", ["user_id"])
    op.create_table(
        "aa_shares",
        sa.Column("share_id", sa.Uuid(), primary_key=True),
        sa.Column("request_id", sa.Uuid(), sa.ForeignKey("aa_requests.request_id"), nullable=False),
        sa.Column("user_id", sa.String(255), nullable=False),
        sa.Column("display_name", sa.String(100), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("amount_cents", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("workflow_id", sa.Uuid(), sa.ForeignKey("workflows.id"), unique=True),
        sa.Column("operation_id", sa.Uuid(), sa.ForeignKey("operations.id"), unique=True),
        sa.UniqueConstraint("request_id", "user_id", name="uq_aa_participant"),
        sa.CheckConstraint("amount_cents > 0", name="ck_aa_positive_share"),
    )
    op.create_index("ix_aa_shares_request_id", "aa_shares", ["request_id"])
    op.create_index("ix_aa_shares_user_id", "aa_shares", ["user_id"])
    op.add_column("mock_bank_transfers", sa.Column("destination_user_id", sa.String(255)))
    op.add_column("mock_bank_transfers", sa.Column("destination_account_id", sa.String(255)))
    op.add_column("mock_bank_transfers", sa.Column("aa_share_id", sa.Uuid()))
    op.add_column("mock_bank_transfers", sa.Column("credited_at", sa.DateTime(timezone=True)))
    op.create_unique_constraint("uq_mock_transfer_aa_share", "mock_bank_transfers", ["aa_share_id"])


def downgrade():
    op.drop_constraint("uq_mock_transfer_aa_share", "mock_bank_transfers", type_="unique")
    for column in ["credited_at", "aa_share_id", "destination_account_id", "destination_user_id"]:
        op.drop_column("mock_bank_transfers", column)
    op.drop_table("aa_shares")
    op.drop_table("aa_requests")
