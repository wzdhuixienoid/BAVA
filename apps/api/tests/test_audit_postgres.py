import pytest
import test_postgres_integration
from test_audit_evidence import test_unknown_reconcile_preserves_historical_unknown as unknown_case
from test_plan_postgres import use_postgres

postgres_factory = test_postgres_integration.postgres_factory
pytestmark = pytest.mark.postgres


async def test_postgres_audit_unknown_reconcile_history_round_trip(app, postgres_factory):
    await use_postgres(app, postgres_factory)
    await unknown_case(app)
