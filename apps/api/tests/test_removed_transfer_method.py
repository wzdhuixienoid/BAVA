import importlib.util
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from pydantic import ValidationError
from sqlalchemy import inspect, select
from test_postgres_integration import postgres_factory as postgres_factory
from test_transfer_payee_shortcuts import create_draft

from banking_api.persistence.models import WorkflowModel
from banking_api.workflows.transfer.models import TransferIntent, TransferWorkflowState


async def test_removed_endpoints_and_intent_are_unavailable(app, client):
    schema = app.openapi()
    assert not any("phone" in path for path in schema["paths"])
    for path in ["/api/v1/payees/resolve-phone", "/api/v1/payees/phone-recipients"]:
        assert (await client.post(path, json={})).status_code in {404, 405}
    with pytest.raises(ValidationError):
        TransferIntent(recipient_phone="13800138000", amount="1")


async def test_retirement_migration_cancels_unsubmitted_and_keeps_bank_workflows(
    app, postgres_factory
):
    app.state.test_session_factory = postgres_factory
    _, pending = await create_draft(app, TransferIntent(amount="1", source_account_hint="工资卡"))
    _, bank = await create_draft(
        app, TransferIntent(recipient_query="李小雨", amount="1", source_account_hint="工资卡")
    )
    async with postgres_factory() as session:
        row = await session.get(WorkflowModel, pending.workflow_id)
        state = dict(row.state_json)
        state["draft"] = {
            **state["draft"],
            "phone_token": "retired-token",
            "masked_phone": "138****8000",
            "phone_lookup_started": True,
        }
        state["required_input"] = {"type": "RECIPIENT_PHONE", "options": [], "message": "old input"}
        row.state_json = state
        await session.commit()
    directory = Path(__file__).resolve().parents[1] / "migrations" / "versions"

    def migration(conn):
        context = MigrationContext.configure(conn)
        with Operations.context(context):
            for name in [
                "0024_phone_routing",
                "0027_phone_recipients",
                "0028_remove_phone_transfers",
            ]:
                tables = set(inspect(conn).get_table_names())
                if name.startswith("0024") and "phone_routes" in tables:
                    continue
                if name.startswith("0027") and "phone_recipients" in tables:
                    continue
                spec = importlib.util.spec_from_file_location(name, directory / f"{name}.py")
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)
                module.upgrade()
        assert not {"phone_routes", "phone_recipients", "phone_lookup_limits"} & set(
            inspect(conn).get_table_names()
        )

        retired = (
            conn.execute(
                select(WorkflowModel.__table__).where(
                    WorkflowModel.workflow_id == pending.workflow_id
                )
            )
            .mappings()
            .one()
        )
        assert retired["status"].value == "CANCELLED"
        assert "phone_token" not in retired["state_json"]["draft"]
        TransferWorkflowState.model_validate(retired["state_json"])
        preserved = (
            conn.execute(
                select(WorkflowModel.__table__).where(WorkflowModel.workflow_id == bank.workflow_id)
            )
            .mappings()
            .one()
        )
        assert preserved["status"].value == "READY_FOR_REVIEW"

    async with postgres_factory.kw["bind"].connect() as conn:
        transaction = await conn.begin()
        try:
            await conn.run_sync(migration)
        finally:
            await transaction.rollback()
