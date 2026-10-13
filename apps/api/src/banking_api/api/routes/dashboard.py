from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, Query, Request

from banking_api.api.dependencies import PrincipalDependency, SessionDependency
from banking_api.config.demo_time import reference_now
from banking_api.domain.account import AccountBalanceResult
from banking_api.domain.dashboard import (
    DashboardSnapshot,
    DashboardTransaction,
    DashboardTransactionPage,
)
from banking_api.financial.analysis_snapshot import FinancialAnalysisSnapshot, ToolEvidence
from banking_api.financial.analytics_service import FinancialAnalyticsService
from banking_api.financial.anomaly_detector import TransactionAnomalyDetector
from banking_api.financial.errors import FinancialDomainError
from banking_api.financial.models import TopTransaction
from banking_api.financial.report_formatter import ReportFormatter
from banking_api.skills.monthly_spending_report import MonthlySpendingReportSkill
from banking_api.subscriptions.service import SubscriptionAnalysisService

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


def display_transaction(item: TopTransaction) -> DashboardTransaction:
    return DashboardTransaction(
        transaction_id=item.transaction_id,
        merchant=item.merchant,
        description=item.description,
        category=item.category,
        amount=item.amount,
        amount_display=ReportFormatter().money(item.amount, item.currency),
        occurred_at=item.occurred_at,
        account_id=item.account_id,
        currency=item.currency,
    )


@router.get("/transactions", response_model=DashboardTransactionPage)
async def get_transactions(
    request: Request,
    principal: PrincipalDependency,
    month: str | None = Query(default=None, pattern=r"^\d{4}-\d{2}$"),
    year: int | None = Query(default=None, ge=1, le=9998),
    month_number: int | None = Query(default=None, ge=1, le=12),
    category: str | None = Query(default=None, max_length=50),
    account_id: str | None = Query(default=None, max_length=100),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=100),
) -> DashboardTransactionPage:
    try:
        page = FinancialAnalyticsService(request.app.state.mock_bank).spending_transactions(
            user_id=principal.user_id,
            as_of=reference_now(),
            month=month,
            year=year,
            month_number=month_number,
            category=category,
            account_id=account_id,
            offset=offset,
            limit=limit,
        )
    except FinancialDomainError as exc:
        raise HTTPException(
            status_code=422, detail={"code": exc.code.value, "message": exc.message}
        ) from exc
    return DashboardTransactionPage(
        transactions=[display_transaction(item) for item in page.transactions],
        total_count=page.total_count,
        offset=page.offset,
        available_months=page.available_months,
        available_categories=page.available_categories,
    )


@router.get("", response_model=DashboardSnapshot)
async def get_dashboard(
    request: Request,
    session: SessionDependency,
    principal: PrincipalDependency,
    month: str = Query(default="2026-08", pattern=r"^\d{4}-\d{2}$"),
) -> DashboardSnapshot:
    """Principal-scoped read projection; reuse existing analytics and Provider balance."""
    bank = request.app.state.mock_bank
    user_id = principal.user_id
    analytics = FinancialAnalyticsService(bank)
    now = datetime.now(UTC)
    try:
        snapshot = FinancialAnalysisSnapshot(
            period=month,
            account_ids=[],
            spending_summary=analytics.spending_summary(month, user_id=user_id),
            category_breakdown=analytics.category_breakdown(month, user_id=user_id),
            period_comparison=analytics.compare_periods(month, user_id=user_id),
            top_transactions=analytics.top_transactions(month, user_id=user_id),
            tool_evidence=[
                ToolEvidence(capability_id=capability, input={"month": month})
                for capability in (
                    "transaction.spending_summary",
                    "transaction.category_breakdown",
                    "transaction.compare_periods",
                    "transaction.top_transactions",
                )
            ],
        )
    except FinancialDomainError as exc:
        raise HTTPException(
            status_code=422, detail={"code": exc.code.value, "message": exc.message}
        ) from exc
    accounts = []
    for account in bank.list_accounts(user_id=user_id)[:100]:
        values = bank.get_balance(account["account_id"], user_id=user_id)
        values["balance"] = await request.app.state.transfer_provider.effective_balance(
            user_id, account["account_id"]
        )
        accounts.append(AccountBalanceResult(**values, as_of=datetime.now(UTC)))
    return DashboardSnapshot(
        accounts=accounts,
        recent_transactions=[
            display_transaction(item)
            for item in analytics.recent_spending(user_id=user_id, as_of=reference_now())
        ],
        spending=MonthlySpendingReportSkill().build_core(snapshot),
        subscriptions=await SubscriptionAnalysisService(bank, session).analyze(
            user_id=user_id, generated_at=reference_now(), upcoming_days=30
        ),
        anomalies=TransactionAnomalyDetector(bank).detect(
            user_id=user_id, generated_at=reference_now()
        ),
        as_of=now,
    )
