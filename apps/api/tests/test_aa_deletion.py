from uuid import UUID

import pytest
from sqlalchemy import func, select
from test_aa_collections import aa_runtime, pay, published_request

from banking_api.api.dependencies import get_current_principal
from banking_api.application.aa_service import AAService
from banking_api.application.operation_service import OperationActionError
from banking_api.domain.principal import Principal
from banking_api.persistence.models import (
    AARequestModel,
    AAShareModel,
    ConversationModel,
    EventModel,
    OperationModel,
)
from banking_api.transfers.provider import TransferProviderFaultMode

OWNER = "dev-user-001"


async def cancel_all(app, bank, engine, row):
    async with app.state.test_session_factory() as session:
        service = AAService(session, app.state.event_bus, engine, bank)
        for share in row["shares"]:
            if share["status"] != "SELF_PAID":
                row = await service.close_share(UUID(share["share_id"]), OWNER, row["version"])
        return row


async def test_delete_api_keeps_evidence_and_participant_history(app, client):
    bank, provider, engine = await aa_runtime(app)
    row = await cancel_all(app, bank, engine, await published_request(app, bank, engine))
    request_id = UUID(row["request_id"])
    assert row["status"] == "CANCELLED" and row["can_delete"]
    stale = await client.request(
        "DELETE", f"/api/v1/aa-requests/{request_id}", json={"expected_version": row["version"] - 1}
    )
    assert stale.status_code == 409 and "VERSION_CONFLICT" in stale.text
    response = await client.request(
        "DELETE", f"/api/v1/aa-requests/{request_id}", json={"expected_version": row["version"]}
    )
    assert response.status_code == 204
    assert (await client.get("/api/v1/aa-requests")).json() == []
    snapshot = (await client.get(f"/api/v1/aa-requests/{request_id}")).json()
    assert snapshot["deleted_from_list"] and not snapshot["can_delete"]
    assert snapshot["snapshot"] == row["snapshot"]
    async with app.state.test_session_factory() as session:
        service = AAService(session, app.state.event_bus, engine, bank)
        participant_rows = await service.list("mock-zhangsan")
        assert len(participant_rows) == 1 and not participant_rows[0]["deleted_from_list"]
        assert not participant_rows[0]["can_delete"]
        assert (await session.get(AARequestModel, request_id)).deleted_at is not None
        assert await session.scalar(select(func.count()).select_from(AAShareModel)) == 3
        assert await session.scalar(select(func.count()).select_from(OperationModel)) == 0
        events = (
            await session.scalars(
                select(EventModel).where(EventModel.event_type == "aa.deleted_from_list")
            )
        ).all()
        assert len(events) == 1 and events[0].data_json["aa_request_id"] == str(request_id)
        before = await session.scalar(select(func.count()).select_from(ConversationModel))
        with pytest.raises(OperationActionError, match="NOT_PAYABLE"):
            await service.payment(
                UUID(row["shares"][0]["share_id"]),
                "mock-zhangsan",
                snapshot["version"],
                "acc_salary",
            )
        assert await session.scalar(select(func.count()).select_from(ConversationModel)) == before
    assert await provider.transfer_count() == 0
    replay = await client.request(
        "DELETE", f"/api/v1/aa-requests/{request_id}", json={"expected_version": row["version"]}
    )
    assert replay.status_code == 409


@pytest.mark.parametrize("viewer", ["outsider", "mock-zhangsan"])
async def test_only_initiator_can_delete(app, client, viewer):
    bank, _, engine = await aa_runtime(app)
    row = await cancel_all(app, bank, engine, await published_request(app, bank, engine))
    app.dependency_overrides[get_current_principal] = lambda: Principal(viewer, "test", viewer)
    response = await client.request(
        "DELETE",
        f"/api/v1/aa-requests/{row['request_id']}",
        json={"expected_version": row["version"]},
    )
    assert response.status_code == 404
    async with app.state.test_session_factory() as session:
        assert (await session.get(AARequestModel, UUID(row["request_id"]))).deleted_at is None


@pytest.mark.parametrize(
    "status", ["PENDING", "PAID", "PROCESSING", "UNKNOWN", "FAILED", "REJECTED", "EXPIRED"]
)
async def test_any_non_cancelled_share_blocks_deletion(app, status):
    bank, _, engine = await aa_runtime(app)
    row = await cancel_all(app, bank, engine, await published_request(app, bank, engine))
    async with app.state.test_session_factory() as session:
        share = await session.get(AAShareModel, UUID(row["shares"][0]["share_id"]))
        share.status = status
        await session.commit()
        service = AAService(session, app.state.event_bus, engine, bank)
        assert not (await service.get(UUID(row["request_id"]), OWNER))["can_delete"]
        with pytest.raises(OperationActionError, match="ONLY_FULLY_CANCELLED"):
            await service.delete_cancelled(UUID(row["request_id"]), OWNER, row["version"])
        assert (await session.get(AARequestModel, UUID(row["request_id"]))).deleted_at is None


@pytest.mark.parametrize(
    "fault",
    [
        TransferProviderFaultMode.SUCCESS,
        TransferProviderFaultMode.DEFINITIVE_FAILURE,
        TransferProviderFaultMode.TIMEOUT_AFTER_ACCEPT,
    ],
)
async def test_submitted_payment_prevents_deletion_even_with_stale_cancelled_status(app, fault):
    bank, _, engine = await aa_runtime(app, fault)
    row = await published_request(app, bank, engine)
    await pay(app, bank, engine, row, "mock-zhangsan", row["shares"][0]["share_id"])
    async with app.state.test_session_factory() as session:
        # Simulate a legacy/inconsistent status without erasing the submitted evidence.
        shares = (await session.scalars(select(AAShareModel))).all()
        for share in shares:
            if share.status != "SELF_PAID":
                share.status = "CANCELLED"
                share.operation_id = None
        await session.commit()
        service = AAService(session, app.state.event_bus, engine, bank)
        assert not (await service.get(UUID(row["request_id"]), OWNER))["can_delete"]
        with pytest.raises(OperationActionError, match="ONLY_FULLY_CANCELLED"):
            await service.delete_cancelled(UUID(row["request_id"]), OWNER, row["version"])
