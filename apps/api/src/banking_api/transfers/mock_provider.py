import asyncio
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import func, select
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


class MockTransferProvider:
    """Persistent mock-bank boundary with provider-side idempotency."""

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

    async def submit_transfer(
        self, request: TransferProviderRequest
    ) -> TransferSubmissionResult:
        lock = self._account_locks.setdefault(request.source_account_id, asyncio.Lock())
        async with lock:
            existing = await self._find(request.idempotency_key)
            if existing is not None:
                return self._submission_from(existing)

            now = datetime.now(UTC)
            provider_reference = f"mocktr_{uuid4().hex}"
            status = (
                "FAILED"
                if self.fault_mode is TransferProviderFaultMode.DEFINITIVE_FAILURE
                else "SUCCEEDED"
            )
            error_code = "PROVIDER_REJECTED" if status == "FAILED" else None
            try:
                async with self._session_factory() as session:
                    async with session.begin():
                        existing = (
                            await session.execute(
                                select(MockBankTransferModel)
                                .where(
                                    MockBankTransferModel.idempotency_key
                                    == request.idempotency_key
                                )
                                .with_for_update()
                            )
                        ).scalar_one_or_none()
                        if existing is not None:
                            return self._submission_from(existing)
                        available = await self._effective_balance_in_session(
                            session, request.source_account_id
                        )
                        if available < request.amount:
                            status = "FAILED"
                            error_code = "INSUFFICIENT_FUNDS"
                        transfer = MockBankTransferModel(
                            provider_reference=provider_reference,
                            idempotency_key=request.idempotency_key,
                            source_account_id=request.source_account_id,
                            payee_id=request.payee_id,
                            amount=request.amount,
                            currency=request.currency,
                            status=status,
                            applied_at=now if status == "SUCCEEDED" else None,
                            created_at=now,
                        )
                        session.add(transfer)
                        await session.flush()
            except IntegrityError:
                existing = await self._find(request.idempotency_key)
                if existing is None:
                    raise
                return self._submission_from(existing)

            if (
                self.fault_mode is TransferProviderFaultMode.TIMEOUT_AFTER_ACCEPT
                and status == "SUCCEEDED"
            ):
                raise TransferProviderAmbiguousError
            if status == "FAILED":
                return TransferSubmissionResult(
                    outcome=TransferSubmissionOutcome.FAILED,
                    provider_reference=provider_reference,
                    error_code=error_code,
                    error_message="Mock provider definitively rejected the transfer",
                )
            return TransferSubmissionResult(
                outcome=TransferSubmissionOutcome.ACCEPTED,
                provider_reference=provider_reference,
            )

    async def get_transfer_status(
        self, *, idempotency_key: UUID, provider_reference: str | None
    ) -> TransferProviderStatus:
        transfer = await self._find(idempotency_key)
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
            error_code="PROVIDER_REJECTED",
            error_message="Mock provider definitively rejected the transfer",
        )

    async def effective_balance(self, account_id: str) -> Decimal:
        async with self._session_factory() as session:
            return await self._effective_balance_in_session(session, account_id)

    async def transfer_count(self) -> int:
        async with self._session_factory() as session:
            return int(
                (
                    await session.execute(
                        select(func.count()).select_from(MockBankTransferModel)
                    )
                ).scalar_one()
            )

    async def _find(self, idempotency_key: UUID) -> MockBankTransferModel | None:
        async with self._session_factory() as session:
            return (
                await session.execute(
                    select(MockBankTransferModel).where(
                        MockBankTransferModel.idempotency_key == idempotency_key
                    )
                )
            ).scalar_one_or_none()

    async def _effective_balance_in_session(
        self, session: AsyncSession, account_id: str
    ) -> Decimal:
        base = Decimal(str(self._bank.get_balance(account_id)["balance"]))
        debited = (
            await session.execute(
                select(func.coalesce(func.sum(MockBankTransferModel.amount), 0)).where(
                    MockBankTransferModel.source_account_id == account_id,
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
            error_code="PROVIDER_REJECTED",
            error_message="Mock provider definitively rejected the transfer",
        )
