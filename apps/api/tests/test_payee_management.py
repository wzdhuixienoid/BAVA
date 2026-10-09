from sqlalchemy import select
from test_transfer_payee_shortcuts import create_draft

from banking_api.api.dependencies import get_current_principal
from banking_api.domain.principal import Principal
from banking_api.payees.service import PayeeService
from banking_api.persistence.models import PayeeModel
from banking_api.workflows.transfer.models import TransferIntent


async def test_edit_created_payee_preserves_or_replaces_account_and_delete_hides_it(app, client):
    body = {
        "display_name": "测试收款人",
        "bank_name": "星河银行（虚构）",
        "account_number": "6222021234566789",
        "confirmed": True,
    }
    created = (await client.post("/api/v1/payees", json=body)).json()
    url = f"/api/v1/payees/{created['payee_id']}"
    edit = {
        "display_name": "新姓名",
        "bank_name": body["bank_name"],
        "phone_alias": "新别名",
        "confirmed": True,
    }
    response = await client.patch(url, json=edit)
    assert response.status_code == 200
    assert response.json()["masked_account"] == "****6789"
    assert response.json()["payee_id"] == created["payee_id"]
    edit["account_number"] = "6222021111114321"
    changed = (await client.patch(url, json=edit)).json()
    assert changed["masked_account"] == "****4321"
    assert edit["account_number"] not in str(changed)
    async with app.state.test_session_factory() as session:
        service = PayeeService(app.state.mock_bank, session)
        assert len(await service.search("新别名", user_id="dev-user-001")) == 1
        assert not await service.search("测试收款人", user_id="dev-user-001")
    assert (await client.delete(url)).status_code == 204
    assert (await client.delete(url)).status_code == 204
    assert not (await client.get("/api/v1/payees", params={"query": "新姓名"})).json()
    assert (await client.patch(url, json=edit)).status_code == 404
    async with app.state.test_session_factory() as session:
        row = await session.get(PayeeModel, created["payee_id"])
        assert row.deleted_at is not None
        assert not await PayeeService(app.state.mock_bank, session).search(
            "新别名", user_id="dev-user-001"
        )


async def test_fixture_edits_and_deletions_persist_with_original_public_id(app, client):
    items = (await client.get("/api/v1/payees")).json()
    fixture = items[0]
    url = f"/api/v1/payees/{fixture['payee_id']}"
    edit = {
        "display_name": "修改后的张三",
        "bank_name": fixture["bank_name"],
        "account_number": None,
        "confirmed": True,
    }
    updated = (await client.patch(url, json=edit)).json()
    assert updated["payee_id"] == fixture["payee_id"]
    assert updated["masked_account"] == fixture["masked_account"]
    refreshed = (await client.get("/api/v1/payees")).json()
    assert len(refreshed) == len(items)
    assert (
        next(item for item in refreshed if item["payee_id"] == fixture["payee_id"])["display_name"]
        == edit["display_name"]
    )
    assert (await client.delete(url)).status_code == 204
    refreshed = (await client.get("/api/v1/payees")).json()
    assert fixture["payee_id"] not in {item["payee_id"] for item in refreshed}
    async with app.state.test_session_factory() as session:
        record = (
            await session.execute(
                select(PayeeModel).where(PayeeModel.source_payee_id == fixture["payee_id"])
            )
        ).scalar_one()
        assert record.deleted_at is not None


async def test_edit_delete_cannot_access_another_users_payee(app, client):
    created = (
        await client.post(
            "/api/v1/payees",
            json={
                "display_name": "私有收款人",
                "bank_name": "星河银行（虚构）",
                "account_number": "6222021234566789",
                "confirmed": True,
            },
        )
    ).json()
    app.dependency_overrides[get_current_principal] = lambda: Principal(
        user_id="other-user", issuer="test", subject="other-user"
    )
    url = f"/api/v1/payees/{created['payee_id']}"
    edit = {"display_name": "非法修改", "bank_name": "星河银行（虚构）", "confirmed": True}
    assert (await client.patch(url, json=edit)).status_code == 404
    assert (await client.delete(url)).status_code == 404
    assert (await client.get("/api/v1/payees")).json() == []


async def test_edit_requires_confirmation_and_rejects_duplicate_account(app, client):
    base = {"display_name": "同名", "bank_name": "星河银行（虚构）", "confirmed": True}
    first = (
        await client.post("/api/v1/payees", json=base | {"account_number": "6222021234566789"})
    ).json()
    second = (
        await client.post("/api/v1/payees", json=base | {"account_number": "6222029999996789"})
    ).json()
    url = f"/api/v1/payees/{second['payee_id']}"
    assert (await client.patch(url, json=base | {"confirmed": False})).status_code == 409
    assert (
        await client.patch(url, json=base | {"account_number": "6222021234566789"})
    ).status_code == 409
    items = (await client.get("/api/v1/payees", params={"query": "同名"})).json()
    assert {item["payee_id"] for item in items} == {first["payee_id"], second["payee_id"]}


async def test_payee_in_unfinished_transfer_cannot_be_changed_or_deleted(app, client):
    _, workflow = await create_draft(
        app,
        TransferIntent(
            recipient_query="李小雨",
            amount="1.00",
            source_account_hint="工资卡",
        ),
    )
    payee_id = workflow.state["draft"]["payee_id"]
    url = f"/api/v1/payees/{payee_id}"
    edit = {"display_name": "新名字", "bank_name": "星河银行（虚构）", "confirmed": True}
    for response in [await client.patch(url, json=edit), await client.delete(url)]:
        assert response.status_code == 409
        assert response.json()["detail"] == "PAYEE_HAS_ACTIVE_TRANSFER"
    items = (await client.get("/api/v1/payees", params={"query": "李小雨"})).json()
    assert len(items) == 1 and items[0]["payee_id"] == payee_id
