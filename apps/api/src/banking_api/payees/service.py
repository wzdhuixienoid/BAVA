from __future__ import annotations

from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from banking_api.mock_bank.service import MockBankService
from banking_api.persistence.models import PayeeModel
from banking_api.tools.models import PayeeSummary

MOCK_BANKS = ("星河银行（虚构）", "蓝海银行（虚构）", "森林银行（虚构）", "远山银行（虚构）")


class PayeeCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    display_name: str = Field(min_length=1, max_length=100)
    bank_name: str = Field(min_length=1, max_length=100)
    account_suffix: str = Field(pattern=r"^[0-9]{4}$")
    phone_alias: str = Field(default="", max_length=100)
    confirmed: bool

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


class PayeeService:
    def __init__(self, bank: MockBankService, session: AsyncSession) -> None:
        self.bank, self.session = bank, session

    @staticmethod
    def summary(row: PayeeModel) -> PayeeSummary:
        return PayeeSummary(
            payee_id=row.payee_id,
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
        fixture = [
            PayeeSummary.model_validate(row) for row in self.bank.list_payees(user_id=user_id)
        ]
        items = fixture + [self.summary(row) for row in rows]
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
        normalized = self.bank._normalize(query)
        items = await self.list(user_id=user_id, query=query)
        return [
            row
            for row in items
            if normalized
            in {self.bank._normalize(row.display_name), self.bank._normalize(row.phone_alias)}
        ][:10]

    async def create(self, body: PayeeCreate, *, user_id: str) -> PayeeSummary:
        if not body.confirmed:
            raise ValueError("PAYEE_CONFIRMATION_REQUIRED")
        items = await self.list(user_id=user_id)
        for item in items:
            if (item.display_name, item.bank_name, item.masked_account) == (
                body.display_name,
                body.bank_name,
                f"****{body.account_suffix}",
            ):
                return item
        row = PayeeModel(
            payee_id=f"payee_{uuid4().hex}",
            user_id=user_id,
            display_name=body.display_name,
            bank_name=body.bank_name,
            account_suffix=body.account_suffix,
            phone_alias=body.phone_alias,
        )
        try:
            async with self.session.begin_nested():
                self.session.add(row)
                await self.session.flush()
        except IntegrityError:
            row = (
                await self.session.execute(
                    select(PayeeModel).where(
                        PayeeModel.user_id == user_id,
                        PayeeModel.display_name == body.display_name,
                        PayeeModel.bank_name == body.bank_name,
                        PayeeModel.account_suffix == body.account_suffix,
                    )
                )
            ).scalar_one()
        return self.summary(row)
