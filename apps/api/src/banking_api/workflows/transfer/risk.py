from datetime import date, datetime
from decimal import Decimal

from banking_api.domain.risk import (
    BusinessRiskLevel,
    RiskReasonCode,
    TransferRiskDecision,
)

TRANSFER_DAILY_RISK_THRESHOLD = Decimal("1000.00")


class TransferRiskCurrencyUnsupportedError(Exception):
    code = "TRANSFER_RISK_CURRENCY_UNSUPPORTED"
    message = "比赛环境转账风险策略仅支持 CNY，不支持其他币种或换汇。"

    def __init__(self) -> None:
        super().__init__(self.message)


class TransferRiskPolicy:
    """Deterministic transfer control policy. It never consumes LLM output."""

    def __init__(self, threshold: Decimal = TRANSFER_DAILY_RISK_THRESHOLD) -> None:
        self.threshold = threshold

    @staticmethod
    def require_supported_currency(currency: str) -> None:
        if currency != "CNY":
            raise TransferRiskCurrencyUnsupportedError

    def evaluate(
        self,
        *,
        requested_amount: Decimal,
        currency: str,
        business_date: date,
        successful_transfer_total_today: Decimal,
        in_flight_transfer_exposure_today: Decimal,
        evaluated_at: datetime,
        persistent_authorization: bool = False,
        passwordless_limit: Decimal = Decimal("200.00"),
    ) -> TransferRiskDecision:
        self.require_supported_currency(currency)
        projected = (
            successful_transfer_total_today + in_flight_transfer_exposure_today + requested_amount
        )
        level = (
            BusinessRiskLevel.RED
            if persistent_authorization
            or projected > self.threshold
            or requested_amount >= passwordless_limit
            else BusinessRiskLevel.YELLOW
        )
        reason_codes = []
        if persistent_authorization:
            reason_codes.append(RiskReasonCode.FUNDS_OUTFLOW_REQUIRES_REAUTH)
        if projected > self.threshold:
            reason_codes.append(RiskReasonCode.DAILY_TRANSFER_LIMIT_EXCEEDED)
        if requested_amount >= passwordless_limit:
            reason_codes.append(RiskReasonCode.PASSWORDLESS_LIMIT_REACHED)
        if not reason_codes:
            reason_codes.append(RiskReasonCode.DAILY_TRANSFER_WITHIN_LIMIT)
        return TransferRiskDecision(
            level=level,
            required_approval=True,
            required_reauthentication=level is BusinessRiskLevel.RED,
            reason_codes=reason_codes,
            business_date=business_date,
            currency=currency,
            daily_successful_total=successful_transfer_total_today,
            daily_in_flight_exposure=in_flight_transfer_exposure_today,
            requested_amount=requested_amount,
            projected_daily_total=projected,
            threshold=self.threshold,
            evaluated_at=evaluated_at,
            passwordless_limit=passwordless_limit,
        )

    @staticmethod
    def retain_stricter(
        previous: TransferRiskDecision | None,
        fresh: TransferRiskDecision,
        *,
        at_commit: bool = False,
    ) -> TransferRiskDecision:
        if previous is None or previous.level is not BusinessRiskLevel.RED:
            if (
                previous is not None
                and previous.level is BusinessRiskLevel.YELLOW
                and fresh.level is BusinessRiskLevel.RED
                and at_commit
            ):
                fresh.reason_codes.append(RiskReasonCode.RISK_ESCALATED_AT_COMMIT)
            return fresh
        if fresh.level is BusinessRiskLevel.RED:
            return fresh
        fresh.level = BusinessRiskLevel.RED
        fresh.required_reauthentication = True
        fresh.reason_codes.append(RiskReasonCode.RISK_NOT_DOWNGRADED)
        return fresh
