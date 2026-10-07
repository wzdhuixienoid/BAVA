"""Remember manually chosen conversation titles."""

import sqlalchemy as sa
from alembic import op

revision = "0019"
down_revision = "0018"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "conversations",
        sa.Column(
            "title_is_custom",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.execute(
        sa.text(
            "UPDATE conversations SET title_is_custom = true "
            "WHERE title NOT IN ('新对话', '订阅管理')"
        )
    )


def downgrade() -> None:
    op.drop_column("conversations", "title_is_custom")
