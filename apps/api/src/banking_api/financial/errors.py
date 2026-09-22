from enum import StrEnum


class FinancialErrorCode(StrEnum):
    INVALID_PERIOD = "INVALID_PERIOD"
    ACCOUNT_NOT_FOUND = "ACCOUNT_NOT_FOUND"
    NO_TRANSACTIONS_IN_PERIOD = "NO_TRANSACTIONS_IN_PERIOD"
    MIXED_CURRENCY_UNSUPPORTED = "MIXED_CURRENCY_UNSUPPORTED"


class FinancialDomainError(Exception):
    def __init__(self, code: FinancialErrorCode, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
