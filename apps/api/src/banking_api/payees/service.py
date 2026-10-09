from __future__ import annotations

from datetime import UTC, datetime
from hashlib import sha256
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from banking_api.domain.enums import WorkflowStatus
from banking_api.mock_bank.service import MockBankService
from banking_api.persistence.models import PayeeModel, WorkflowModel
from banking_api.tools.models import PayeeSummary

MOCK_BANKS = ("星河银行（虚构）", "蓝海银行（虚构）", "森林银行（虚构）", "远山银行（虚构）")


class PayeeCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    display_name: str = Field(min_length=1, max_length=100)
    bank_name: str = Field(min_length=1, max_length=100)
    account_number: str = Field(pattern=r"^[0-9]{12,32}$")
    phone_alias: str = Field(default="", max_length=100)
    confirmed: bool

    @field_validator("account_number", mode="before")
    @classmethod
    def normalize_account_number(cls, value: str) -> str:
        return "".join(value.split()) if isinstance(value, str) else value

    @field_validator("display_name", "bank_name", "phone_alias", mode="before")
    @classmethod
    def strip_value(cls, value: str) -> str:
        return value.strip()

    @field_validator("bank_name")
    @classmethod
    def mock_bank_only(cls, value: str) -> str:
        if value not in MOCK_BANKS:
            raise ValueError("请选择虚构收款银行")
        return value


class PayeeUpdate(PayeeCreate):
    account_number: str | None = Field(default=None, pattern=r"^[0-9]{12,32}$")


class PayeeService:
    def __init__(self, bank: MockBankService, session: AsyncSession) -> None:
        self.bank, self.session = bank, session

    @staticmethod
    def summary(row: PayeeModel) -> PayeeSummary:
        return PayeeSummary(
            payee_id=row.source_payee_id or row.payee_id,
            display_name=row.display_name,
            bank_name=row.bank_name,
            masked_account=f"****{row.account_suffix}",
            phone_alias=row.phone_alias,
        )

    async def list(
        self, *, user_id: str, query: str | None = None, limit: int = 100, offset: int = 0
    ) -> list[PayeeSummary]:
        rows = (
            await self.session.execute(
                select(PayeeModel)
                .where(PayeeModel.user_id == user_id)
                .order_by(PayeeModel.created_at, PayeeModel.payee_id)
            )
        ).scalars()
        rows = list(rows)
        overridden = {row.source_payee_id for row in rows if row.source_payee_id}
        fixture = [
            PayeeSummary.model_validate(row)
            for row in self.bank.list_payees(user_id=user_id)
            if row["payee_id"] not in overridden
        ]
        items = fixture + [self.summary(row) for row in rows if row.deleted_at is None]
        if query:
            normalized = self.bank._normalize(query)
            items = [
                row
                for row in items
                if normalized in self.bank._normalize(row.display_name)
                or normalized in self.bank._normalize(row.phone_alias)
            ]
        return items[offset : offset + limit]

    async def search(self, query: str, *, user_id: str) -> list[PayeeSummary]:
        if not self.bank._normalize(query):
            return []
        items = await self.list(user_id=user_id, query=query)
        exact = [
            row
            for row in items
            if self.bank._normalize(query)
            in {self.bank._normalize(row.display_name), self.bank._normalize(row.phone_alias)}
        ]
        return (exact or items)[:10]

    async def create(self, body: PayeeCreate, *, user_id: str) -> PayeeSummary:
        if not body.confirmed:
            raise ValueError("PAYEE_CONFIRMATION_REQUIRED")
        # Mock transfers address payee IDs. Keep only a fingerprint and display suffix,
        # so accounts sharing a last-four value remain distinct without storing plaintext.
        fingerprint = sha256(body.account_number.encode("ascii")).hexdigest()
        identity = (
            PayeeModel.user_id == user_id,
            PayeeModel.display_name == body.display_name,
            PayeeModel.bank_name == body.bank_name,
            PayeeModel.account_fingerprint == fingerprint,
        )
        existing = (
            await self.session.execute(select(PayeeModel).where(*identity))
        ).scalar_one_or_none()
        if existing is not None:
            existing.deleted_at = None
            existing.phone_alias = body.phone_alias
            return self.summary(existing)
        row = PayeeModel(
            payee_id=f"payee_{uuid4().hex}",
            user_id=user_id,
            display_name=body.display_name,
            bank_name=body.bank_name,
            account_suffix=body.account_number[-4:],
            account_fingerprint=fingerprint,
            phone_alias=body.phone_alias,
        )
        try:
            async with self.session.begin_nested():
                self.session.add(row)
                await self.session.flush()
        except IntegrityError:
            row = (await self.session.execute(select(PayeeModel).where(*identity))).scalar_one()
        return self.summary(row)

    async def _editable(self, payee_id: str, *, user_id: str) -> PayeeModel:
        row = (
            await self.session.execute(
                select(PayeeModel).where(
                    PayeeModel.user_id == user_id,
                    or_(PayeeModel.payee_id == payee_id, PayeeModel.source_payee_id == payee_id),
                )
            )
        ).scalar_one_or_none()
        if row is not None:
            return row
        fixture = next(
            (
                item
                for item in self.bank.list_payees(user_id=user_id)
                if item["payee_id"] == payee_id
            ),
            None,
        )
        if fixture is None:
            raise LookupError("PAYEE_NOT_FOUND")
        row = PayeeModel(
            payee_id=f"payee_{uuid4().hex}",
            source_payee_id=payee_id,
            user_id=user_id,
            display_name=fixture["display_name"],
            bank_name=fixture["bank_name"],
            account_suffix=fixture["masked_account"][-4:],
            phone_alias=fixture.get("phone_alias", ""),
        )
        self.session.add(row)
        await self.session.flush()
        return row

    async def update(self, payee_id: str, body: PayeeUpdate, *, user_id: str) -> PayeeSummary:
        if not body.confirmed:
            raise ValueError("PAYEE_CONFIRMATION_REQUIRED")
        row = await self._editable(payee_id, user_id=user_id)
        if row.deleted_at is not None:
            raise LookupError("PAYEE_NOT_FOUND")
        await self._require_unused(payee_id, user_id=user_id)
        try:
            async with self.session.begin_nested():
                row.display_name, row.bank_name, row.phone_alias = (
                    body.display_name,
                    body.bank_name,
                    body.phone_alias,
                )
                if body.account_number is not None:
                    row.account_suffix = body.account_number[-4:]
                    row.account_fingerprint = sha256(
                        body.account_number.encode("ascii")
                    ).hexdigest()
                await self.session.flush()
        except IntegrityError as exc:
            raise ValueError("PAYEE_ALREADY_EXISTS") from exc
        return self.summary(row)

    async def delete(self, payee_id: str, *, user_id: str) -> None:
        row = await self._editable(payee_id, user_id=user_id)
        await self._require_unused(payee_id, user_id=user_id)
        row.deleted_at = row.deleted_at or datetime.now(UTC)

    async def _require_unused(self, payee_id: str, *, user_id: str) -> None:
        workflows = (
            await self.session.execute(
                select(WorkflowModel).where(
                    WorkflowModel.user_id == user_id,
                    WorkflowModel.status.not_in(
                        [
                            WorkflowStatus.SUCCEEDED,
                            WorkflowStatus.FAILED,
                            WorkflowStatus.CANCELLED,
                        ]
                    ),
                )
            )
        ).scalars()
        if any(row.state_json.get("draft", {}).get("payee_id") == payee_id for row in workflows):
            raise ValueError("PAYEE_HAS_ACTIVE_TRANSFER")
