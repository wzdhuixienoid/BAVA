"""Retire phone transfer capability without deleting financial evidence."""

import sqlalchemy as sa
from alembic import op

revision = "0028"
down_revision = "0027"
branch_labels = None
depends_on = None


def upgrade():
    conn = op.get_bind()
    meta = sa.MetaData()
    workflows = sa.Table("workflows", meta, autoload_with=conn)
    operations = sa.Table("operations", meta, autoload_with=conn)
    approvals = sa.Table("approvals", meta, autoload_with=conn)
    grants = sa.Table("scheduled_authorizations", meta, autoload_with=conn)
    schedules = sa.Table("scheduled_transfers", meta, autoload_with=conn)
    tasks = sa.Table("tasks", meta, autoload_with=conn)
    retired = {
        "phone_token",
        "masked_phone",
        "phone_input_invalid",
        "phone_lookup_started",
        "phone_routing_version",
    }
    for row in conn.execute(sa.select(workflows)).mappings().all():
        state = row["state_json"]
        if not isinstance(state, dict) or not isinstance(state.get("draft"), dict):
            continue
        draft = state["draft"]
        is_phone = bool(draft.get("phone_token") or draft.get("phone_input_invalid"))
        state = dict(state)
        state["draft"] = {k: v for k, v in draft.items() if k not in retired}
        if isinstance(state.get("review_payload"), dict):
            state["review_payload"] = {
                k: v for k, v in state["review_payload"].items() if k not in retired
            }
        required = state.get("required_input") or {}
        if required.get("type") == "RECIPIENT_PHONE":
            state["required_input"] = None
        values = {"state_json": state}
        if is_phone:
            operation = (
                conn.execute(sa.select(operations).where(operations.c.workflow_id == row["id"]))
                .mappings()
                .first()
            )
            stop = operation is None
            if operation and operation["status"] == "CREATED":
                if operation["reconcile_attempts"] == 0:
                    conn.execute(
                        operations.update()
                        .where(operations.c.id == operation["id"])
                        .values(
                            status="FAILED",
                            error_code="TRANSFER_METHOD_REMOVED",
                            error_message="Transfer method removed before submission",
                            completed_at=sa.func.now(),
                            next_reconcile_at=None,
                            version=operations.c.version + 1,
                        )
                    )
                    stop = True
                else:
                    # Acceptance may already have happened. Query the original Operation only.
                    conn.execute(
                        operations.update()
                        .where(operations.c.id == operation["id"])
                        .values(
                            status="UNKNOWN",
                            next_reconcile_at=sa.func.now(),
                            version=operations.c.version + 1,
                        )
                    )
            if stop and row["status"] not in {"SUCCEEDED", "FAILED", "CANCELLED"}:
                values.update(status="CANCELLED", version=row["version"] + 1)
                state["required_input"] = state["validation"] = None
                conn.execute(
                    approvals.update()
                    .where(approvals.c.workflow_id == row["id"], approvals.c.status == "APPROVED")
                    .values(status="INVALIDATED", invalidated_at=sa.func.now())
                )
                conn.execute(
                    grants.update()
                    .where(grants.c.workflow_id == row["id"], grants.c.used_at.is_(None))
                    .values(revoked_at=sa.func.now())
                )
                conn.execute(
                    schedules.update()
                    .where(schedules.c.workflow_id == row["id"], schedules.c.operation_id.is_(None))
                    .values(
                        status="CANCELLED",
                        error_code="TRANSFER_METHOD_REMOVED",
                        version=schedules.c.version + 1,
                    )
                )
                conn.execute(
                    tasks.update()
                    .where(
                        tasks.c.id == row["source_task_id"],
                        tasks.c.status.not_in(["COMPLETED", "FAILED", "CANCELLED"]),
                    )
                    .values(status="CANCELLED")
                )
        conn.execute(workflows.update().where(workflows.c.id == row["id"]).values(**values))
    op.drop_table("phone_recipients")
    op.drop_table("phone_lookup_limits")
    op.drop_table("phone_routes")


def downgrade():
    # Schema rollback is supported; deleted data and authorizations stay retired.
    # Historical upgrade routines restore empty tables for older migrations.
    import importlib.util
    from pathlib import Path

    for filename in ["0024_phone_routing.py", "0027_phone_recipients.py"]:
        path = Path(__file__).with_name(filename)
        spec = importlib.util.spec_from_file_location(f"rollback_{path.stem}", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        module.upgrade()
