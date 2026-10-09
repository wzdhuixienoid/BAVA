"""Accept full account identities while displaying only their last four digits."""

import sqlalchemy as sa
from alembic import op

revision = "0021"
down_revision = "0020"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("payees", sa.Column("account_fingerprint", sa.String(64), nullable=True))
    op.drop_constraint("uq_payee_identity", "payees", type_="unique")
    op.create_unique_constraint(
        "uq_payee_identity",
        "payees",
        ["user_id", "display_name", "bank_name", "account_fingerprint"],
    )


def downgrade() -> None:
    op.drop_constraint("uq_payee_identity", "payees", type_="unique")
    op.create_unique_constraint(
        "uq_payee_identity",
        "payees",
        ["user_id", "display_name", "bank_name", "account_suffix"],
    )
    op.drop_column("payees", "account_fingerprint")
