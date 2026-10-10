"""New-business switch is independent of already accepted settlement."""

from banking_api.config.settings import get_settings
from banking_api.wealth.calculation import WealthError


def mock_execution_allowed():
    return get_settings().app_environment in {"development", "test"}


def feature_status():
    allowed = mock_execution_allowed() and get_settings().mock_wealth_enabled
    return {
        "new_business_allowed": allowed,
        "reason": "模拟理财已启用" if allowed else "已暂停新理财交易，已受理订单继续处理",
    }


def require_new_business():
    if not feature_status()["new_business_allowed"]:
        raise WealthError("WEALTH_DISABLED", "已暂停新理财交易，订单未受理；已受理订单继续处理")
