from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, Query, Request

from banking_api.api.dependencies import PrincipalDependency, SessionDependency
from banking_api.domain.account import AccountBalanceResult
from banking_api.domain.dashboard import DashboardSnapshot
from banking_api.financial.analysis_snapshot import FinancialAnalysisSnapshot, ToolEvidence
from banking_api.financial.analytics_service import FinancialAnalyticsService
from banking_api.financial.anomaly_detector import TransactionAnomalyDetector
from banking_api.financial.errors import FinancialDomainError
from banking_api.skills.monthly_spending_report import MonthlySpendingReportSkill
from banking_api.subscriptions.service import SubscriptionAnalysisService

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


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
        spending=MonthlySpendingReportSkill().build_core(snapshot),
        subscriptions=await SubscriptionAnalysisService(bank, session).analyze(
            user_id=user_id, generated_at=now, upcoming_days=30
        ),
        anomalies=TransactionAnomalyDetector(bank).detect(user_id=user_id, generated_at=now),
        as_of=now,
    )
