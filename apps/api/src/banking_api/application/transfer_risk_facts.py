from dataclasses import dataclass
from datetime import UTC, date, datetime, time
from decimal import Decimal
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from banking_api.domain.enums import OperationStatus
from banking_api.domain.operation import OperationType
from banking_api.persistence.models import MockBankTransferModel, OperationModel


@dataclass(frozen=True, slots=True)
class TransferRiskFacts:
    business_date: date
    successful_total: Decimal
    in_flight_exposure: Decimal


class TransferRiskFactsService:
    """Computes user-scoped daily transfer exposure from authoritative persistence."""

    def __init__(self, session: AsyncSession, *, business_timezone: str) -> None:
        self.session = session
        self.timezone = ZoneInfo(business_timezone)

    async def for_user(
        self, *, user_id: str, currency: str, evaluated_at: datetime
    ) -> TransferRiskFacts:
        instant = (
            evaluated_at
            if evaluated_at.tzinfo is not None
            else evaluated_at.replace(tzinfo=UTC)
        )
        local_date = instant.astimezone(self.timezone).date()
        start = datetime.combine(local_date, time.min, self.timezone).astimezone(UTC)
        end = datetime.combine(local_date, time.max, self.timezone).astimezone(UTC)

        provider_rows = list(
            (
                await self.session.execute(
                    select(MockBankTransferModel).where(
                        MockBankTransferModel.user_id == user_id,
                        MockBankTransferModel.currency == currency,
                        MockBankTransferModel.created_at >= start,
                        MockBankTransferModel.created_at <= end,
                    )
                )
            ).scalars()
        )
        successful = sum(
            (
                Decimal(str(row.amount))
                for row in provider_rows
                if row.status == "SUCCEEDED"
                and row.applied_at is not None
                and start <= self._as_utc(row.applied_at) <= end
            ),
            Decimal("0"),
        )
        provider_terminal_keys = {
            row.idempotency_key for row in provider_rows if row.status in {"SUCCEEDED", "FAILED"}
        }

        operations = list(
            (
                await self.session.execute(
                    select(OperationModel).where(
                        OperationModel.user_id == user_id,
                        OperationModel.operation_type == OperationType.TRANSFER,
                        OperationModel.status.in_(
                            (
                                OperationStatus.CREATED,
                                OperationStatus.SUBMITTED,
                                OperationStatus.UNKNOWN,
                            )
                        ),
                        OperationModel.created_at >= start,
                        OperationModel.created_at <= end,
                    )
                )
            ).scalars()
        )
        in_flight = sum(
            (
                Decimal(str(operation.payload_json["amount"]))
                for operation in operations
                if operation.idempotency_key not in provider_terminal_keys
                and operation.payload_json.get("currency") == currency
            ),
            Decimal("0"),
        )
        return TransferRiskFacts(
            business_date=local_date,
            successful_total=successful,
            in_flight_exposure=in_flight,
        )

    @staticmethod
    def _as_utc(value: datetime) -> datetime:
        return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
