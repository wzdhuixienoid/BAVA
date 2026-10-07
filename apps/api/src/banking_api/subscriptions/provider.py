import asyncio
import hashlib
from datetime import UTC, datetime
from enum import StrEnum
from uuid import UUID, uuid4

from pydantic import BaseModel
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from banking_api.mock_bank.service import MockBankService
from banking_api.persistence.models import (
    MockSubscriptionActionModel,
    MockSubscriptionCancellationModel,
    MockSubscriptionStateModel,
)
from banking_api.subscriptions.contracts import effective_contracts, next_billing, utc


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
    expected_version: int | None = None
    next_billing_at: datetime | None = None


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
        self._locks: dict[str, asyncio.Lock] = {}

    async def cancel(
        self, request: SubscriptionCancellationRequest
    ) -> SubscriptionCancellationResult:
        return await self._apply(request, "SUBSCRIPTION_CANCEL")

    async def resume(
        self, request: SubscriptionCancellationRequest
    ) -> SubscriptionCancellationResult:
        return await self._apply(request, "SUBSCRIPTION_RESUME")

    async def _apply(
        self, request: SubscriptionCancellationRequest, action: str
    ) -> SubscriptionCancellationResult:
        key = f"{request.user_id}:{request.subscription_id}"
        async with self._locks.setdefault(key, asyncio.Lock()):
            try:
                async with self.session_factory() as session:
                    async with session.begin():
                        if session.get_bind().dialect.name == "postgresql":
                            digest = hashlib.sha256(f"mock-subscription:{key}".encode()).digest()
                            await session.execute(
                                text("SELECT pg_advisory_xact_lock(:key)"),
                                {"key": int.from_bytes(digest[:8], "big", signed=True)},
                            )
                        existing = await self._find_in_session(
                            session, request.user_id, request.idempotency_key
                        )
                        if existing is not None:
                            return self._result(existing)
                        contracts = await effective_contracts(self.bank, session, request.user_id)
                        contract = next(
                            (
                                c
                                for c in contracts
                                if c["subscription_id"] == request.subscription_id
                            ),
                            None,
                        )
                        now = datetime.now(UTC)
                        error = None
                        if contract is None:
                            error = "SUBSCRIPTION_NOT_FOUND"
                        elif (
                            request.expected_version is not None
                            and contract["version"] != request.expected_version
                        ):
                            error = "SUBSCRIPTION_VERSION_CONFLICT"
                        elif action == "SUBSCRIPTION_CANCEL" and contract["status"] == "CANCELLED":
                            error = "ALREADY_CANCELLED"
                        elif action == "SUBSCRIPTION_CANCEL" and not contract["cancellable"]:
                            error = "SUBSCRIPTION_NOT_CANCELLABLE"
                        elif action == "SUBSCRIPTION_RESUME" and contract["status"] == "ACTIVE":
                            error = "ALREADY_ACTIVE"
                        elif action == "SUBSCRIPTION_RESUME" and not contract["resumable"]:
                            error = "SUBSCRIPTION_NOT_RESUMABLE"
                        elif (
                            action == "SUBSCRIPTION_RESUME"
                            and request.next_billing_at is not None
                            and utc(request.next_billing_at) <= now
                        ):
                            error = "SUBSCRIPTION_BILLING_DATE_EXPIRED"
                        elif self.fault_mode is SubscriptionProviderFaultMode.DEFINITIVE_FAILURE:
                            error = "PROVIDER_REJECTED"
                        row = MockSubscriptionActionModel(
                            provider_reference=f"mocksub_{uuid4().hex}",
                            user_id=request.user_id,
                            subscription_id=request.subscription_id,
                            idempotency_key=request.idempotency_key,
                            action=action,
                            status="FAILED" if error else "SUCCEEDED",
                            error_code=error,
                            created_at=now,
                            completed_at=now,
                        )
                        session.add(row)
                        if error is None:
                            state = await session.get(
                                MockSubscriptionStateModel,
                                (request.user_id, request.subscription_id),
                            )
                            if state is None:
                                state = MockSubscriptionStateModel(
                                    user_id=request.user_id,
                                    subscription_id=request.subscription_id,
                                    status=contract["status"],
                                    version=contract["version"],
                                )
                                session.add(state)
                            state.status = (
                                "ACTIVE" if action == "SUBSCRIPTION_RESUME" else "CANCELLED"
                            )
                            state.version = contract["version"] + 1
                            state.next_billing_at = (
                                (request.next_billing_at or next_billing(contract, now))
                                if action == "SUBSCRIPTION_RESUME"
                                else (
                                    utc(
                                        datetime.fromisoformat(
                                            str(contract["next_billing_at"]).replace("Z", "+00:00")
                                        )
                                    )
                                    if contract.get("next_billing_at")
                                    else None
                                )
                            )
                            state.updated_at = now
            except IntegrityError:
                existing = await self._find(request.user_id, request.idempotency_key)
                if existing is None:
                    raise
                return self._result(existing)
            result = self._result(row)
            if (
                self.fault_mode is SubscriptionProviderFaultMode.TIMEOUT_AFTER_ACCEPT
                and row.status == "SUCCEEDED"
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
            old = await session.scalar(
                select(func.count()).select_from(MockSubscriptionCancellationModel)
            )
            new = await session.scalar(
                select(func.count())
                .select_from(MockSubscriptionActionModel)
                .where(MockSubscriptionActionModel.action == "SUBSCRIPTION_CANCEL")
            )
            return int(old or 0) + int(new or 0)

    async def _find(self, user_id: str, idempotency_key: UUID):
        async with self.session_factory() as session:
            return await self._find_in_session(session, user_id, idempotency_key)

    @staticmethod
    async def _find_in_session(session, user_id, idempotency_key):
        for model in (MockSubscriptionActionModel, MockSubscriptionCancellationModel):
            row = (
                await session.execute(
                    select(model).where(
                        model.user_id == user_id, model.idempotency_key == idempotency_key
                    )
                )
            ).scalar_one_or_none()
            if row is not None:
                return row
        return None

    @staticmethod
    def _result(row: MockSubscriptionCancellationModel) -> SubscriptionCancellationResult:
        return SubscriptionCancellationResult(
            outcome="ACCEPTED" if row.status == "SUCCEEDED" else "FAILED",
            provider_reference=row.provider_reference,
            error_code=row.error_code,
            error_message=row.error_code if row.status == "FAILED" else None,
        )
