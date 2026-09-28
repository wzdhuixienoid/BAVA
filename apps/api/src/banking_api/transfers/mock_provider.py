import asyncio
import hashlib
import logging
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from banking_api.mock_bank.service import MockBankService
from banking_api.persistence.models import MockBankTransferModel
from banking_api.transfers.provider import (
    TransferProviderAmbiguousError,
    TransferProviderFaultMode,
    TransferProviderRequest,
    TransferProviderStatus,
    TransferProviderStatusValue,
    TransferSubmissionOutcome,
    TransferSubmissionResult,
)

logger = logging.getLogger(__name__)


def provider_account_lock_key(source_account_id: str, user_id: str = "dev-user-001") -> int:
    """Map one provider account to a stable signed PostgreSQL advisory-lock key."""

    # Keep the v0.5.2 account-serialization key stable; user scoping is enforced
    # by provider queries and balance calculations, not by changing lock identity.
    digest = hashlib.sha256(
        f"mock-transfer-provider:source-account:{source_account_id}".encode()
    ).digest()
    return int.from_bytes(digest[:8], byteorder="big", signed=True)


class MockTransferProvider:
    """Persistent mock-bank boundary with idempotency and account serialization."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        bank: MockBankService,
        *,
        fault_mode: TransferProviderFaultMode = TransferProviderFaultMode.SUCCESS,
    ) -> None:
        self._session_factory = session_factory
        self._bank = bank
        self.fault_mode = fault_mode
        self._account_locks: dict[str, asyncio.Lock] = {}

    async def submit_transfer(self, request: TransferProviderRequest) -> TransferSubmissionResult:
        authority_key = f"{request.user_id}:{request.source_account_id}"
        lock = self._account_locks.setdefault(authority_key, asyncio.Lock())
        async with lock:
            existing = await self._find(request.user_id, request.idempotency_key)
            if existing is not None:
                logger.info("mock provider idempotent replay")
                return self._submission_from(existing)
            try:
                result = await self._submit_in_provider_transaction(request)
            except IntegrityError:
                existing = await self._find(request.user_id, request.idempotency_key)
                if existing is None:
                    raise
                logger.info("mock provider idempotent replay after uniqueness conflict")
                return self._submission_from(existing)

            if (
                self.fault_mode is TransferProviderFaultMode.TIMEOUT_AFTER_ACCEPT
                and result.outcome is TransferSubmissionOutcome.ACCEPTED
            ):
                raise TransferProviderAmbiguousError
            return result

    async def _submit_in_provider_transaction(
        self, request: TransferProviderRequest
    ) -> TransferSubmissionResult:
        now = datetime.now(UTC)
        async with self._session_factory() as session:
            async with session.begin():
                await self._serialize_source_account(
                    session, request.source_account_id, request.user_id
                )
                existing = (
                    await session.execute(
                        select(MockBankTransferModel)
                        .where(
                            MockBankTransferModel.idempotency_key == request.idempotency_key,
                            MockBankTransferModel.user_id == request.user_id,
                        )
                        .with_for_update()
                    )
                ).scalar_one_or_none()
                if existing is not None:
                    logger.info("mock provider idempotent replay inside serialized transaction")
                    return self._submission_from(existing)

                status = (
                    "FAILED"
                    if self.fault_mode is TransferProviderFaultMode.DEFINITIVE_FAILURE
                    else "SUCCEEDED"
                )
                error_code = "PROVIDER_REJECTED" if status == "FAILED" else None
                error_message = (
                    "Mock provider definitively rejected the transfer"
                    if status == "FAILED"
                    else None
                )
                available = await self._effective_balance_in_session(
                    session, request.user_id, request.source_account_id
                )
                if available < request.amount:
                    status = "FAILED"
                    error_code = "INSUFFICIENT_FUNDS"
                    error_message = "Insufficient available balance"
                transfer = MockBankTransferModel(
                    provider_reference=f"mocktr_{uuid4().hex}",
                    idempotency_key=request.idempotency_key,
                    user_id=request.user_id,
                    source_account_id=request.source_account_id,
                    payee_id=request.payee_id,
                    amount=request.amount,
                    currency=request.currency,
                    status=status,
                    error_code=error_code,
                    error_message=error_message,
                    applied_at=now if status == "SUCCEEDED" else None,
                    created_at=now,
                )
                session.add(transfer)
                await session.flush()
                if status == "SUCCEEDED":
                    logger.info("mock provider transfer accepted")
                elif error_code == "INSUFFICIENT_FUNDS":
                    logger.info("mock provider transfer rejected: insufficient funds")
                else:
                    logger.info("mock provider transfer definitively rejected")
                return self._submission_from(transfer)

    @staticmethod
    async def _serialize_source_account(
        session: AsyncSession, source_account_id: str, user_id: str = "dev-user-001"
    ) -> None:
        bind = session.get_bind()
        if bind.dialect.name != "postgresql":
            return
        lock_key = provider_account_lock_key(source_account_id, user_id)
        logger.info("mock provider waiting for account serialization lock_key=%s", lock_key)
        await session.execute(
            text("SELECT pg_advisory_xact_lock(:lock_key)"),
            {"lock_key": lock_key},
        )
        logger.info("mock provider account serialization acquired lock_key=%s", lock_key)

    async def get_transfer_status(
        self,
        *,
        user_id: str,
        idempotency_key: UUID,
        provider_reference: str | None,
    ) -> TransferProviderStatus:
        transfer = await self._find(user_id, idempotency_key)
        if transfer is None:
            return TransferProviderStatus(status=TransferProviderStatusValue.UNKNOWN)
        if provider_reference is not None and transfer.provider_reference != provider_reference:
            return TransferProviderStatus(status=TransferProviderStatusValue.UNKNOWN)
        if transfer.status == "SUCCEEDED":
            return TransferProviderStatus(
                status=TransferProviderStatusValue.SUCCEEDED,
                provider_reference=transfer.provider_reference,
            )
        return TransferProviderStatus(
            status=TransferProviderStatusValue.FAILED,
            provider_reference=transfer.provider_reference,
            error_code=transfer.error_code or "PROVIDER_REJECTED",
            error_message=transfer.error_message
            or "Mock provider definitively rejected the transfer",
        )

    async def effective_balance(self, user_id: str, account_id: str) -> Decimal:
        async with self._session_factory() as session:
            return await self._effective_balance_in_session(session, user_id, account_id)

    async def transfer_count(self) -> int:
        async with self._session_factory() as session:
            return int(
                (
                    await session.execute(select(func.count()).select_from(MockBankTransferModel))
                ).scalar_one()
            )

    async def _find(self, user_id: str, idempotency_key: UUID) -> MockBankTransferModel | None:
        async with self._session_factory() as session:
            return (
                await session.execute(
                    select(MockBankTransferModel).where(
                        MockBankTransferModel.idempotency_key == idempotency_key,
                        MockBankTransferModel.user_id == user_id,
                    )
                )
            ).scalar_one_or_none()

    async def _effective_balance_in_session(
        self, session: AsyncSession, user_id: str, account_id: str
    ) -> Decimal:
        base = Decimal(str(self._bank.get_balance(account_id, user_id=user_id)["balance"]))
        debited = (
            await session.execute(
                select(func.coalesce(func.sum(MockBankTransferModel.amount), 0)).where(
                    MockBankTransferModel.source_account_id == account_id,
                    MockBankTransferModel.user_id == user_id,
                    MockBankTransferModel.status == "SUCCEEDED",
                )
            )
        ).scalar_one()
        return base - Decimal(str(debited))

    @staticmethod
    def _submission_from(transfer: MockBankTransferModel) -> TransferSubmissionResult:
        if transfer.status == "SUCCEEDED":
            return TransferSubmissionResult(
                outcome=TransferSubmissionOutcome.ACCEPTED,
                provider_reference=transfer.provider_reference,
            )
        return TransferSubmissionResult(
            outcome=TransferSubmissionOutcome.FAILED,
            provider_reference=transfer.provider_reference,
            error_code=transfer.error_code or "PROVIDER_REJECTED",
            error_message=transfer.error_message
            or "Mock provider definitively rejected the transfer",
        )
