from datetime import datetime

from pydantic import BaseModel, Field

from banking_api.domain.account import AccountBalanceResult
from banking_api.domain.risk import BusinessRiskLevel
from banking_api.financial.anomaly_models import TransactionAnomalySnapshot
from banking_api.financial.report_models import MonthlySpendingReportCore
from banking_api.subscriptions.models import SubscriptionAnalysisSnapshot


class DashboardSnapshot(BaseModel):
    accounts: list[AccountBalanceResult] = Field(max_length=100)
    spending: MonthlySpendingReportCore
    subscriptions: SubscriptionAnalysisSnapshot
    anomalies: TransactionAnomalySnapshot
    risk_level: BusinessRiskLevel = BusinessRiskLevel.GREEN
    as_of: datetime
