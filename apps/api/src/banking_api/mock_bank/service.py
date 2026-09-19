from dataclasses import dataclass


@dataclass(frozen=True)
class AccountSummary:
    account_id: str
    display_name: str
    currency: str
    balance: str


class MockBankService:
    """A minimal read-only bank backend stub, not a registered agent tool."""

    _accounts = (
        AccountSummary("account-6688", "工资卡 ****6688", "CNY", "12000.00"),
        AccountSummary("account-1024", "储蓄卡 ****1024", "CNY", "50000.00"),
    )

    def list_accounts(self) -> tuple[AccountSummary, ...]:
        return self._accounts

    def get_account_summary(self, account_id: str) -> AccountSummary | None:
        return next((item for item in self._accounts if item.account_id == account_id), None)

