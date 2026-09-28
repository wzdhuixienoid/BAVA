from datetime import UTC, datetime
from enum import StrEnum
from uuid import UUID, uuid4

from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from banking_api.mock_bank.service import MockBankService
from banking_api.persistence.models import MockSubscriptionCancellationModel


class SubscriptionProviderFaultMode(StrEnum):
    SUCCESS = "SUCCESS"
    TIMEOUT_AFTER_ACCEPT = "TIMEOUT_AFTER_ACCEPT"
    DEFINITIVE_FAILURE = "DEFINITIVE_FAILURE"


class SubscriptionProviderAmbiguousError(Exception):
    pass


class SubscriptionCancellationRequest(BaseModel):
    user_id: str
    subscription_id: str
    idempotency_key: UUID


class SubscriptionCancellationResult(BaseModel):
    outcome: str
    provider_reference: str | None = None
    error_code: str | None = None
    error_message: str | None = None


class SubscriptionCancellationStatus(BaseModel):
    status: str
    provider_reference: str | None = None
    error_code: str | None = None
    error_message: str | None = None


class MockSubscriptionProvider:
    """Official persistent subscription provider for the synthetic banking environment."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        bank: MockBankService,
        *,
        fault_mode: SubscriptionProviderFaultMode = SubscriptionProviderFaultMode.SUCCESS,
    ) -> None:
        self.session_factory = session_factory
        self.bank = bank
        self.fault_mode = fault_mode

    async def cancel(
        self, request: SubscriptionCancellationRequest
    ) -> SubscriptionCancellationResult:
        existing = await self._find(request.user_id, request.idempotency_key)
        if existing is not None:
            return self._result(existing)
        contract = self.bank.get_subscription(request.subscription_id, user_id=request.user_id)
        now = datetime.now(UTC)
        status = "SUCCEEDED"
        error_code = None
        if contract is None:
            status, error_code = "FAILED", "SUBSCRIPTION_NOT_FOUND"
        elif contract["status"] == "CANCELLED":
            status, error_code = "FAILED", "ALREADY_CANCELLED"
        elif not contract["cancellable"]:
            status, error_code = "FAILED", "SUBSCRIPTION_NOT_CANCELLABLE"
        elif self.fault_mode is SubscriptionProviderFaultMode.DEFINITIVE_FAILURE:
            status, error_code = "FAILED", "PROVIDER_REJECTED"
        row = MockSubscriptionCancellationModel(
            provider_reference=f"mocksub_{uuid4().hex}",
            user_id=request.user_id,
            subscription_id=request.subscription_id,
            idempotency_key=request.idempotency_key,
            status=status,
            error_code=error_code,
            created_at=now,
            completed_at=now,
        )
        try:
            async with self.session_factory() as session:
                session.add(row)
                await session.commit()
        except IntegrityError:
            existing = await self._find(request.user_id, request.idempotency_key)
            if existing is None:
                raise
            return self._result(existing)
        result = self._result(row)
        if (
            self.fault_mode is SubscriptionProviderFaultMode.TIMEOUT_AFTER_ACCEPT
            and status == "SUCCEEDED"
        ):
            raise SubscriptionProviderAmbiguousError
        return result

    async def get_status(
        self,
        *,
        user_id: str,
        idempotency_key: UUID,
        provider_reference: str | None,
    ) -> SubscriptionCancellationStatus:
        row = await self._find(user_id, idempotency_key)
        if row is None or (
            provider_reference is not None and row.provider_reference != provider_reference
        ):
            return SubscriptionCancellationStatus(status="UNKNOWN")
        return SubscriptionCancellationStatus(
            status=row.status,
            provider_reference=row.provider_reference,
            error_code=row.error_code,
            error_message=(row.error_code if row.status == "FAILED" else None),
        )

    async def cancellation_count(self) -> int:
        async with self.session_factory() as session:
            return int(
                (
                    await session.execute(
                        select(func.count()).select_from(MockSubscriptionCancellationModel)
                    )
                ).scalar_one()
            )

    async def _find(
        self, user_id: str, idempotency_key: UUID
    ) -> MockSubscriptionCancellationModel | None:
        async with self.session_factory() as session:
            return (
                await session.execute(
                    select(MockSubscriptionCancellationModel).where(
                        MockSubscriptionCancellationModel.user_id == user_id,
                        MockSubscriptionCancellationModel.idempotency_key == idempotency_key,
                    )
                )
            ).scalar_one_or_none()

    @staticmethod
    def _result(row: MockSubscriptionCancellationModel) -> SubscriptionCancellationResult:
        return SubscriptionCancellationResult(
            outcome="ACCEPTED" if row.status == "SUCCEEDED" else "FAILED",
            provider_reference=row.provider_reference,
            error_code=row.error_code,
            error_message=row.error_code if row.status == "FAILED" else None,
        )
