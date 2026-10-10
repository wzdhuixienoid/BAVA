"""Versioned mock wealth facts. Decimal values never pass through a float."""

from datetime import date, datetime
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import (
    JSON,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column

from banking_api.domain.wealth import ProductRiskGrade  # noqa: F401
from banking_api.persistence.database import Base
from banking_api.persistence.models import utc_now


class WealthProduct(Base):
    __tablename__ = "wealth_products"
    product_id: Mapped[str] = mapped_column(String(40), primary_key=True)
    current_version: Mapped[str] = mapped_column(String(40))


class WealthProductVersion(Base):
    __tablename__ = "wealth_product_versions"
    __table_args__ = (UniqueConstraint("product_id", "version"),)
    version_id: Mapped[str] = mapped_column(String(80), primary_key=True)
    product_id: Mapped[str] = mapped_column(ForeignKey("wealth_products.product_id"))
    version: Mapped[str] = mapped_column(String(40))
    name: Mapped[str] = mapped_column(String(100))
    risk: Mapped[str] = mapped_column(String(2))
    terms: Mapped[dict] = mapped_column(JSON)
    content_hash: Mapped[str] = mapped_column(String(64))
    effective_from: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    effective_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class WealthNav(Base):
    __tablename__ = "wealth_navs"
    __table_args__ = (UniqueConstraint("product_id", "nav_date"), CheckConstraint("nav > 0"))
    nav_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    product_id: Mapped[str] = mapped_column(ForeignKey("wealth_products.product_id"))
    nav_date: Mapped[date] = mapped_column(Date)
    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    nav: Mapped[Decimal] = mapped_column(Numeric(20, 6))


class WealthDocument(Base):
    __tablename__ = "wealth_documents"
    document_id: Mapped[str] = mapped_column(String(100), primary_key=True)
    product_id: Mapped[str] = mapped_column(ForeignKey("wealth_products.product_id"))
    version_id: Mapped[str] = mapped_column(ForeignKey("wealth_product_versions.version_id"))
    version: Mapped[str] = mapped_column(String(40))
    source: Mapped[str] = mapped_column(String(255))
    effective_from: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    effective_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    section: Mapped[str] = mapped_column(String(100))
    content_hash: Mapped[str] = mapped_column(String(64))
    content: Mapped[str] = mapped_column(Text)
    structured_terms: Mapped[dict] = mapped_column(JSON)


class WealthAssessment(Base):
    __tablename__ = "wealth_assessments"
    assessment_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    user_id: Mapped[str] = mapped_column(String(255), index=True)
    questionnaire_version: Mapped[str] = mapped_column(String(40))
    rules_version: Mapped[str] = mapped_column(String(40))
    answers: Mapped[list] = mapped_column(JSON)
    score: Mapped[int]
    grade: Mapped[int]
    reasons: Mapped[list] = mapped_column(JSON)
    suitable: Mapped[bool]
    invalidated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class WealthPosition(Base):
    __tablename__ = "wealth_positions"
    __table_args__ = (
        UniqueConstraint("user_id", "account_id", "product_id"),
        CheckConstraint("shares >= 0"),
    )
    position_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    user_id: Mapped[str] = mapped_column(String(255), index=True)
    account_id: Mapped[str] = mapped_column(String(100))
    product_id: Mapped[str] = mapped_column(ForeignKey("wealth_products.product_id"))
    shares: Mapped[Decimal] = mapped_column(Numeric(24, 6), default=Decimal(0))


class WealthOrder(Base):
    __tablename__ = "wealth_orders"
    __table_args__ = (CheckConstraint("quantity > 0"),)
    order_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    user_id: Mapped[str] = mapped_column(String(255), index=True)
    workflow_id: Mapped[UUID] = mapped_column(ForeignKey("workflows.id"))
    operation_id: Mapped[UUID] = mapped_column(ForeignKey("operations.id"), unique=True)
    idempotency_key: Mapped[UUID] = mapped_column(Uuid, unique=True)
    provider_reference: Mapped[str] = mapped_column(String(100), unique=True)
    direction: Mapped[str] = mapped_column(String(10))
    account_id: Mapped[str] = mapped_column(String(100))
    product_id: Mapped[str] = mapped_column(ForeignKey("wealth_products.product_id"))
    version_id: Mapped[str] = mapped_column(ForeignKey("wealth_product_versions.version_id"))
    snapshot: Mapped[dict] = mapped_column(JSON)
    quantity: Mapped[Decimal] = mapped_column(Numeric(24, 6))
    status: Mapped[str] = mapped_column(String(20))
    trade_date: Mapped[date] = mapped_column(Date)
    confirm_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    settle_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    actual: Mapped[dict | None] = mapped_column(JSON)
    error_code: Mapped[str | None] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class WealthHold(Base):
    __tablename__ = "wealth_holds"
    __table_args__ = (UniqueConstraint("order_id", "kind"), CheckConstraint("quantity >= 0"))
    hold_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    order_id: Mapped[UUID] = mapped_column(ForeignKey("wealth_orders.order_id"))
    user_id: Mapped[str] = mapped_column(String(255), index=True)
    account_id: Mapped[str] = mapped_column(String(100))
    product_id: Mapped[str] = mapped_column(ForeignKey("wealth_products.product_id"))
    kind: Mapped[str] = mapped_column(String(10))
    quantity: Mapped[Decimal] = mapped_column(Numeric(24, 6))
    active: Mapped[bool] = mapped_column(default=True)


class WealthLedger(Base):
    __tablename__ = "wealth_ledger"
    __table_args__ = (UniqueConstraint("order_id", "action"), CheckConstraint("amount >= 0"))
    ledger_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    order_id: Mapped[UUID] = mapped_column(ForeignKey("wealth_orders.order_id"))
    user_id: Mapped[str] = mapped_column(String(255), index=True)
    account_id: Mapped[str] = mapped_column(String(100))
    action: Mapped[str] = mapped_column(String(30))
    amount: Mapped[Decimal] = mapped_column(Numeric(24, 6))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
