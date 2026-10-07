"""Read-only loopback product preflight; no credentials are printed."""

import argparse
import asyncio
from pathlib import Path
from urllib.parse import urlsplit

from alembic.config import Config
from alembic.script import ScriptDirectory
from banking_api import __version__
from banking_api.config.settings import Settings
from httpx import AsyncClient


def local_url(value: str) -> str:
    parts = urlsplit(value)
    if (
        parts.scheme != "http"
        or parts.hostname not in {"localhost", "127.0.0.1", "::1"}
        or parts.username
        or parts.password
    ):
        raise ValueError(
            "Preflight only supports credential-free local development URLs"
        )
    return value.rstrip("/")


def evaluate(readiness: dict, openapi: dict, head: str) -> dict[str, bool]:
    checks = {
        key: readiness.get(key) is True
        for key in (
            "owner_is_demo_user",
            "expected_accounts_exist",
            "salary_balance_initial",
            "daily_exposure_zero",
            "subscriptions_match_fixture",
            "security_guard_normal",
            "llm_configured",
        )
    }
    checks.update(
        {
            "app_version": readiness.get("version") == __version__,
            "openapi_version": openapi.get("info", {}).get("version") == __version__,
            "alembic_head": readiness.get("database_revision") == head,
            "no_unresolved_operation": readiness.get("unresolved_operations") == 0,
            "mock_provider": readiness.get("provider_mode") == "Mock",
            "mock_reauthentication": readiness.get("reauthentication_mode") == "Mock",
            "business_timezone": readiness.get("business_timezone") == "Asia/Shanghai",
        }
    )
    return checks


async def run(api_url: str, web_url: str) -> dict[str, bool]:
    settings = Settings()
    if settings.app_environment not in {"development", "test"}:
        raise ValueError("Demo preflight is restricted to development/test")
    config = Config(str(Path(__file__).parents[1] / "apps/api/alembic.ini"))
    config.set_main_option(
        "script_location", str(Path(__file__).parents[1] / "apps/api/migrations")
    )
    head = ScriptDirectory.from_config(config).get_current_head()
    async with AsyncClient(timeout=15, trust_env=False) as client:
        api = await client.get(f"{local_url(api_url)}/api/v1/demo/readiness")
        api.raise_for_status()
        schema = await client.get(f"{api_url}/openapi.json")
        schema.raise_for_status()
        checks = evaluate(api.json(), schema.json(), head)
        checks["api_database_reachable"] = True
        web = await client.get(local_url(web_url))
        checks["web_reachable"] = web.status_code == 200
    return checks


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api-url", default="http://localhost:8000")
    parser.add_argument("--web-url", default="http://localhost:3000")
    args = parser.parse_args()
    try:
        checks = await run(args.api_url, args.web_url)
    except Exception as exc:  # noqa: BLE001 - sanitize all startup failures
        # Deliberately no exception text: connection errors can contain credentials.
        print(f"FAIL preflight_unavailable ({type(exc).__name__})")
        raise SystemExit(1) from None
    for key, value in checks.items():
        print(f"{'PASS' if value else 'FAIL'} {key}")
    if not all(checks.values()):
        raise SystemExit(1)
    print("PASS Demo preflight")


if __name__ == "__main__":
    asyncio.run(main())
