"""Clarify that renewal proceeds automatically unless the subscription is cancelled."""

import sqlalchemy as sa
from alembic import op

revision = "0033"
down_revision = "0032"
branch_labels = None
depends_on = None

OLD = "请提前确认是否继续订阅。"
NEW = "如需取消订阅，请在扣费前前往订阅与代扣总览办理取消。"


def update_copy(old, new):
    op.execute(
        sa.text(
            "UPDATE notifications SET message = replace(message, :old, :new) "
            "WHERE kind = 'SUBSCRIPTION_RENEWAL'"
        ).bindparams(old=old, new=new)
    )


def upgrade():
    update_copy(OLD, NEW)


def downgrade():
    update_copy(NEW, OLD)
