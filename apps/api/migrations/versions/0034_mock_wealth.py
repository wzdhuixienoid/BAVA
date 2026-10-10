"""Mock wealth immutable catalog and durable settlement.

Revision ID: 0034
Revises: 0033
"""

import sqlalchemy as sa
from alembic import op

revision = "0034"
down_revision = "0033"
branch_labels = None
depends_on = None


def upgrade():
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE workflow_type ADD VALUE IF NOT EXISTS 'WEALTH_PURCHASE'")
        op.execute("ALTER TYPE workflow_type ADD VALUE IF NOT EXISTS 'WEALTH_REDEEM'")
        op.execute("ALTER TYPE approval_type ADD VALUE IF NOT EXISTS 'WEALTH_PURCHASE'")
        op.execute("ALTER TYPE approval_type ADD VALUE IF NOT EXISTS 'WEALTH_REDEEM'")
        op.execute("ALTER TYPE operation_type ADD VALUE IF NOT EXISTS 'WEALTH_PURCHASE'")
        op.execute("ALTER TYPE operation_type ADD VALUE IF NOT EXISTS 'WEALTH_REDEEM'")
    op.execute("""
CREATE TABLE wealth_assessments (
	assessment_id UUID NOT NULL, 
	user_id VARCHAR(255) NOT NULL, 
	questionnaire_version VARCHAR(40) NOT NULL, 
	rules_version VARCHAR(40) NOT NULL, 
	answers JSON NOT NULL, 
	score INTEGER NOT NULL, 
	grade INTEGER NOT NULL, 
	reasons JSON NOT NULL, 
	suitable BOOLEAN NOT NULL, 
	invalidated_at TIMESTAMP WITH TIME ZONE, 
	expires_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (assessment_id)
)

""")
    op.execute("""CREATE INDEX ix_wealth_assessments_user_id ON wealth_assessments (user_id)""")
    op.execute("""
CREATE TABLE wealth_products (
	product_id VARCHAR(40) NOT NULL, 
	current_version VARCHAR(40) NOT NULL, 
	PRIMARY KEY (product_id)
)

""")
    op.execute("""
CREATE TABLE wealth_navs (
	nav_id UUID NOT NULL, 
	product_id VARCHAR(40) NOT NULL, 
	nav_date DATE NOT NULL, 
	published_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	nav NUMERIC(20, 6) NOT NULL, 
	PRIMARY KEY (nav_id), 
	UNIQUE (product_id, nav_date), 
	CHECK (nav > 0), 
	FOREIGN KEY(product_id) REFERENCES wealth_products (product_id)
)

""")
    op.execute("""CREATE INDEX ix_wealth_navs_published_at ON wealth_navs (published_at)""")
    op.execute("""
CREATE TABLE wealth_positions (
	position_id UUID NOT NULL, 
	user_id VARCHAR(255) NOT NULL, 
	account_id VARCHAR(100) NOT NULL, 
	product_id VARCHAR(40) NOT NULL, 
	shares NUMERIC(24, 6) NOT NULL, 
	PRIMARY KEY (position_id), 
	UNIQUE (user_id, account_id, product_id), 
	CHECK (shares >= 0), 
	FOREIGN KEY(product_id) REFERENCES wealth_products (product_id)
)

""")
    op.execute("""CREATE INDEX ix_wealth_positions_user_id ON wealth_positions (user_id)""")
    op.execute("""
CREATE TABLE wealth_product_versions (
	version_id VARCHAR(80) NOT NULL, 
	product_id VARCHAR(40) NOT NULL, 
	version VARCHAR(40) NOT NULL, 
	name VARCHAR(100) NOT NULL, 
	risk VARCHAR(2) NOT NULL, 
	terms JSON NOT NULL, 
	content_hash VARCHAR(64) NOT NULL, 
	effective_from TIMESTAMP WITH TIME ZONE NOT NULL, 
	effective_to TIMESTAMP WITH TIME ZONE, 
	PRIMARY KEY (version_id), 
	UNIQUE (product_id, version), 
	FOREIGN KEY(product_id) REFERENCES wealth_products (product_id)
)

""")
    op.execute("""
CREATE TABLE wealth_documents (
	document_id VARCHAR(100) NOT NULL, 
	product_id VARCHAR(40) NOT NULL, 
	version_id VARCHAR(80) NOT NULL, 
	version VARCHAR(40) NOT NULL, 
	source VARCHAR(255) NOT NULL, 
	effective_from TIMESTAMP WITH TIME ZONE NOT NULL, 
	effective_to TIMESTAMP WITH TIME ZONE, 
	section VARCHAR(100) NOT NULL, 
	content_hash VARCHAR(64) NOT NULL, 
	content TEXT NOT NULL, 
	structured_terms JSON NOT NULL, 
	PRIMARY KEY (document_id), 
	FOREIGN KEY(product_id) REFERENCES wealth_products (product_id), 
	FOREIGN KEY(version_id) REFERENCES wealth_product_versions (version_id)
)

""")
    op.execute("""
CREATE TABLE wealth_orders (
	order_id UUID NOT NULL, 
	user_id VARCHAR(255) NOT NULL, 
	workflow_id UUID NOT NULL, 
	operation_id UUID NOT NULL, 
	idempotency_key UUID NOT NULL, 
	provider_reference VARCHAR(100) NOT NULL, 
	direction VARCHAR(10) NOT NULL, 
	account_id VARCHAR(100) NOT NULL, 
	product_id VARCHAR(40) NOT NULL, 
	version_id VARCHAR(80) NOT NULL, 
	snapshot JSON NOT NULL, 
	quantity NUMERIC(24, 6) NOT NULL, 
	status VARCHAR(20) NOT NULL, 
	trade_date DATE NOT NULL, 
	confirm_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	settle_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	actual JSON, 
	error_code VARCHAR(100), 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (order_id), 
	CHECK (quantity > 0), 
	FOREIGN KEY(workflow_id) REFERENCES workflows (id), 
	UNIQUE (operation_id), 
	FOREIGN KEY(operation_id) REFERENCES operations (id), 
	UNIQUE (idempotency_key), 
	UNIQUE (provider_reference), 
	FOREIGN KEY(product_id) REFERENCES wealth_products (product_id), 
	FOREIGN KEY(version_id) REFERENCES wealth_product_versions (version_id)
)

""")
    op.execute("""CREATE INDEX ix_wealth_orders_user_id ON wealth_orders (user_id)""")
    op.execute("""
CREATE TABLE wealth_holds (
	hold_id UUID NOT NULL, 
	order_id UUID NOT NULL, 
	user_id VARCHAR(255) NOT NULL, 
	account_id VARCHAR(100) NOT NULL, 
	product_id VARCHAR(40) NOT NULL, 
	kind VARCHAR(10) NOT NULL, 
	quantity NUMERIC(24, 6) NOT NULL, 
	active BOOLEAN NOT NULL, 
	PRIMARY KEY (hold_id), 
	UNIQUE (order_id, kind), 
	CHECK (quantity >= 0), 
	FOREIGN KEY(order_id) REFERENCES wealth_orders (order_id), 
	FOREIGN KEY(product_id) REFERENCES wealth_products (product_id)
)

""")
    op.execute("""CREATE INDEX ix_wealth_holds_user_id ON wealth_holds (user_id)""")
    op.execute("""
CREATE TABLE wealth_ledger (
	ledger_id UUID NOT NULL, 
	order_id UUID NOT NULL, 
	user_id VARCHAR(255) NOT NULL, 
	account_id VARCHAR(100) NOT NULL, 
	action VARCHAR(30) NOT NULL, 
	amount NUMERIC(24, 6) NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (ledger_id), 
	UNIQUE (order_id, action), 
	CHECK (amount >= 0), 
	FOREIGN KEY(order_id) REFERENCES wealth_orders (order_id)
)

""")
    op.execute("""CREATE INDEX ix_wealth_ledger_user_id ON wealth_ledger (user_id)""")


def downgrade():
    connection = op.get_bind()
    if connection.scalar(
        sa.text(
            "SELECT count(*) FROM workflows WHERE workflow_type::text "
            "IN ('WEALTH_PURCHASE', 'WEALTH_REDEEM')"
        )
    ):
        raise RuntimeError("Refusing destructive downgrade with wealth workflows")
    for table in ("wealth_orders", "wealth_positions", "wealth_assessments"):
        if connection.scalar(sa.text(f"SELECT count(*) FROM {table}")):
            raise RuntimeError("Refusing destructive downgrade with wealth business data")
    op.drop_table("wealth_ledger")
    op.drop_table("wealth_holds")
    op.drop_table("wealth_orders")
    op.drop_table("wealth_documents")
    op.drop_table("wealth_product_versions")
    op.drop_table("wealth_positions")
    op.drop_table("wealth_navs")
    op.drop_table("wealth_products")
    op.drop_table("wealth_assessments")
    # PostgreSQL enum values remain: never rebuild shared enums on downgrade.
