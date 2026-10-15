from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from banking_api.domain.account import AccountBalanceResult
from banking_api.domain.risk import BusinessRiskLevel
from banking_api.financial.anomaly_models import TransactionAnomalySnapshot
from banking_api.financial.report_models import MonthlySpendingReportCore, ReportTopTransaction
from banking_api.subscriptions.models import SubscriptionAnalysisSnapshot


class DashboardTransaction(ReportTopTransaction):
    currency: str
    direction: Literal["DEBIT", "CREDIT"] = "DEBIT"
    source: Literal["BANK", "SUBSCRIPTION", "WEALTH", "TRANSFER"] = "BANK"
    counterparty_id: str | None = None
    counterparty_bank: str | None = None
    counterparty_account: str | None = None


class DashboardTransactionPage(BaseModel):
    transactions: list[DashboardTransaction] = Field(max_length=100)
    total_count: int = Field(ge=0)
    offset: int = Field(ge=0)
    available_months: list[str]
    available_categories: list[str]


class DashboardSnapshot(BaseModel):
    accounts: list[AccountBalanceResult] = Field(max_length=100)
    recent_transactions: list[DashboardTransaction] = Field(default_factory=list, max_length=100)
    spending: MonthlySpendingReportCore
    subscriptions: SubscriptionAnalysisSnapshot
    anomalies: TransactionAnomalySnapshot
    risk_level: BusinessRiskLevel = BusinessRiskLevel.GREEN
    as_of: datetime
