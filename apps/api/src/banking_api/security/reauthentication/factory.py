from datetime import UTC, datetime

from banking_api.config.settings import get_settings
from banking_api.security.reauthentication.mock_provider import MockReauthenticationProvider
from banking_api.security.reauthentication.totp_provider import TotpReauthenticationProvider


def reauthentication_provider(session, *, clock=lambda: datetime.now(UTC)):
    settings = get_settings()
    if settings.reauth_provider == "totp":
        return TotpReauthenticationProvider(session, settings, clock=clock)
    if settings.app_environment == "production":
        raise ValueError("Mock reauthentication is forbidden in production")
    return MockReauthenticationProvider(settings.mock_reauth_code)
