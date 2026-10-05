"""Read-only, owner-scoped readiness facts. No reset or new business authority."""

from datetime import UTC, datetime
from decimal import Decimal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict
from sqlalchemy import func, select, text

from banking_api import __version__
from banking_api.api.dependencies import PrincipalDependency, SessionDependency
from banking_api.application.transfer_risk_facts import TransferRiskFactsService
from banking_api.config.settings import get_settings
from banking_api.domain.enums import OperationStatus
from banking_api.persistence.models import OperationModel, SecurityGuardStateModel
from banking_api.subscriptions.provider import MockSubscriptionProvider
from banking_api.subscriptions.service import SubscriptionAnalysisService
from banking_api.transfers.mock_provider import MockTransferProvider

router = APIRouter(prefix="/demo", tags=["demo"])


class DemoReadiness(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: str
    database_revision: str
    owner_is_demo_user: bool
    expected_accounts_exist: bool
    salary_balance_initial: bool
    daily_exposure_zero: bool
    subscriptions_match_fixture: bool
    security_guard_normal: bool
    unresolved_operations: int
    provider_mode: str
    reauthentication_mode: str
    llm_configured: bool
    business_timezone: str
    reference_time: datetime | None


@router.get("/readiness", response_model=DemoReadiness)
async def readiness(request: Request, session: SessionDependency, principal: PrincipalDependency):
    settings = get_settings()
    if settings.app_environment not in {"development", "test"}:
        raise HTTPException(status_code=404, detail="Resource not found")
    user_id = principal.user_id
    bank = request.app.state.mock_bank
    transfer = request.app.state.transfer_provider
    accounts = bank.list_accounts(user_id=user_id)
    account_ids = {a["account_id"] for a in accounts}
    salary = (
        await transfer.effective_balance(user_id, "acc_salary")
        if "acc_salary" in account_ids
        else None
    )
    now = datetime.now(UTC)
    risk = await TransferRiskFactsService(
        session, business_timezone=settings.banking_business_timezone
    ).for_user(user_id=user_id, currency="CNY", evaluated_at=now)
    guard = await session.get(SecurityGuardStateModel, user_id)
    locked_until = guard.locked_until if guard else None
    if locked_until and locked_until.tzinfo is None:
        locked_until = locked_until.replace(tzinfo=UTC)
    unresolved = await session.scalar(
        select(func.count())
        .select_from(OperationModel)
        .where(
            OperationModel.user_id == user_id,
            OperationModel.status.in_(
                [OperationStatus.CREATED, OperationStatus.SUBMITTED, OperationStatus.UNKNOWN]
            ),
        )
    )
    snapshot = await SubscriptionAnalysisService(bank, session).analyze(user_id=user_id)
    actual = {
        s.subscription_id: s.status.value for s in snapshot.subscriptions if s.subscription_id
    }
    expected = {s["subscription_id"]: s["status"] for s in bank.list_subscriptions(user_id=user_id)}
    revision = await session.scalar(text("SELECT version_num FROM alembic_version"))
    return DemoReadiness(
        version=__version__,
        database_revision=revision or "",
        owner_is_demo_user=user_id == "dev-user-001",
        expected_accounts_exist={"acc_salary", "acc_savings", "acc_credit", "acc_travel"}
        <= account_ids,
        salary_balance_initial=salary == Decimal("23864.52"),
        daily_exposure_zero=risk.successful_total == 0 and risk.in_flight_exposure == 0,
        subscriptions_match_fixture=all(
            actual.get(key) == value for key, value in expected.items() if value == "ACTIVE"
        )
        and all(expected.get(key) == value for key, value in actual.items()),
        security_guard_normal=not locked_until or locked_until <= now,
        unresolved_operations=unresolved or 0,
        provider_mode="Mock"
        if isinstance(transfer, MockTransferProvider)
        and isinstance(request.app.state.subscription_provider, MockSubscriptionProvider)
        else "Unsupported",
        # WorkflowService registers only Mock reauthentication.
        reauthentication_mode="Mock",
        llm_configured=bool(settings.llm_base_url and settings.llm_api_key and settings.llm_model),
        business_timezone=settings.banking_business_timezone,
        reference_time=settings.demo_reference_time,
    )
