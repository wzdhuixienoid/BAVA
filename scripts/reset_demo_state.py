"""Scoped development/test reset. Never exposed as an API or an agent tool."""

import argparse
import asyncio
from datetime import UTC, datetime
from uuid import uuid5

from banking_api.config.settings import Settings
from banking_api.persistence.models import (
    ApprovalModel,
    ConversationModel,
    EventModel,
    MessageModel,
    MockBankTransferModel,
    MockSubscriptionActionModel,
    MockSubscriptionCancellationModel,
    MockSubscriptionChargeModel,
    MockSubscriptionStateModel,
    NotificationModel,
    OperationModel,
    OutboxEventModel,
    PayeeModel,
    PlanModel,
    PlanStepModel,
    ReauthenticationModel,
    ReportModel,
    SecurityGuardStateModel,
    SubscriptionNotificationCursorModel,
    TaskModel,
    WorkflowModel,
)
from banking_api.wealth.models import (
    WealthAssessment,
    WealthHold,
    WealthLedger,
    WealthOrder,
    WealthPosition,
)
from sqlalchemy import bindparam, delete, func, or_, select, text, update
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine


def validate_reset(environment: str, workers_stopped: bool, user_id: str) -> None:
    if environment not in {"development", "test"}:
        raise ValueError("Demo reset is forbidden outside development/test")
    if not workers_stopped:
        raise ValueError(
            "Stop API/task/recovery/outbox workers before reset; use --workers-stopped"
        )
    if not user_id.strip():
        raise ValueError("An explicit nonempty --user-id is required")


async def reset_demo_state(
    factory, *, environment: str, workers_stopped: bool, user_id: str
):
    validate_reset(environment, workers_stopped, user_id)
    counts = {}
    async with factory() as session, session.begin():
        now = datetime.now(UTC)
        # An acknowledgement is necessary even if there is no current lease. Refuse active leases.
        for model in (TaskModel, OperationModel):
            active = await session.scalar(
                select(func.count())
                .select_from(model)
                .where(model.user_id == user_id, model.lease_expires_at > now)
            )
            if active:
                raise ValueError(
                    "Active execution lease detected; wait for expiry after stopping workers"
                )
        conversations = select(ConversationModel.conversation_id).where(
            ConversationModel.user_id == user_id
        )
        tasks = list(
            (
                await session.scalars(
                    select(TaskModel).where(TaskModel.user_id == user_id)
                )
            ).all()
        )
        task_attempts = {task.task_id: task.execution_attempts for task in tasks}
        steps = (
            await session.execute(
                select(PlanStepModel.step_id, PlanModel.source_task_id)
                .join(PlanModel, PlanModel.plan_id == PlanStepModel.plan_id)
                .where(PlanModel.user_id == user_id)
            )
        ).all()
        thread_ids = [str(task.task_id) for task in tasks]
        for step_id, source_task_id in steps:
            # Retried Plan reads have independent checkpoint namespaces.
            thread_ids.extend(
                str(uuid5(step_id, str(attempt)))
                for attempt in range(1, task_attempts.get(source_task_id, 0) + 1)
            )
        if session.bind.dialect.name == "postgresql" and thread_ids:
            for table in ("checkpoint_writes", "checkpoint_blobs", "checkpoints"):
                exists = await session.scalar(
                    text("SELECT to_regclass(:table)"), {"table": table}
                )
                if exists:
                    statement = text(
                        f"DELETE FROM {table} WHERE thread_id IN :threads"
                    ).bindparams(bindparam("threads", expanding=True))
                    result = await session.execute(statement, {"threads": thread_ids})
                    counts[table] = result.rowcount
        step_ids = [step_id for step_id, _ in steps]
        if step_ids:
            await session.execute(
                update(PlanStepModel)
                .where(PlanStepModel.step_id.in_(step_ids))
                .values(guard_condition_step_id=None, linked_workflow_id=None)
            )
            # Dependencies cascade in PostgreSQL; explicit delete also covers SQLite test fixtures.
            await session.execute(
                text(
                    "DELETE FROM plan_step_dependencies WHERE step_id IN :ids "
                    "OR depends_on_step_id IN :ids"
                ).bindparams(bindparam("ids", expanding=True)),
                {"ids": step_ids},
            )
            await session.execute(
                delete(PlanStepModel).where(PlanStepModel.step_id.in_(step_ids))
            )
        await session.execute(
            update(ApprovalModel)
            .where(ApprovalModel.user_id == user_id)
            .values(consumed_by_operation_id=None)
        )
        events = select(EventModel.event_id).where(
            EventModel.conversation_id.in_(conversations)
        )
        outbox_leases = await session.scalar(
            select(func.count())
            .select_from(OutboxEventModel)
            .where(
                OutboxEventModel.event_id.in_(events),
                OutboxEventModel.lease_expires_at > now,
            )
        )
        if outbox_leases:
            raise ValueError(
                "Active outbox lease detected; wait for expiry after stopping workers"
            )
        scopes = [
            (WealthLedger, WealthLedger.user_id == user_id),
            (WealthHold, WealthHold.user_id == user_id),
            (WealthOrder, WealthOrder.user_id == user_id),
            (WealthPosition, WealthPosition.user_id == user_id),
            (WealthAssessment, WealthAssessment.user_id == user_id),
            (
                MockSubscriptionChargeModel,
                MockSubscriptionChargeModel.user_id == user_id,
            ),
            (
                SubscriptionNotificationCursorModel,
                SubscriptionNotificationCursorModel.user_id == user_id,
            ),
            (NotificationModel, NotificationModel.user_id == user_id),
            (OutboxEventModel, OutboxEventModel.event_id.in_(events)),
            (EventModel, EventModel.conversation_id.in_(conversations)),
            (PlanModel, PlanModel.user_id == user_id),
            (OperationModel, OperationModel.user_id == user_id),
            (ReauthenticationModel, ReauthenticationModel.user_id == user_id),
            (ApprovalModel, ApprovalModel.user_id == user_id),
            (WorkflowModel, WorkflowModel.user_id == user_id),
            (ReportModel, ReportModel.user_id == user_id),
            (MessageModel, MessageModel.conversation_id.in_(conversations)),
            (
                TaskModel,
                or_(
                    TaskModel.user_id == user_id,
                    TaskModel.conversation_id.in_(conversations),
                ),
            ),
            (ConversationModel, ConversationModel.user_id == user_id),
            (MockBankTransferModel, MockBankTransferModel.user_id == user_id),
            (
                MockSubscriptionCancellationModel,
                MockSubscriptionCancellationModel.user_id == user_id,
            ),
            (
                MockSubscriptionActionModel,
                MockSubscriptionActionModel.user_id == user_id,
            ),
            (MockSubscriptionStateModel, MockSubscriptionStateModel.user_id == user_id),
            (PayeeModel, PayeeModel.user_id == user_id),
            (SecurityGuardStateModel, SecurityGuardStateModel.user_id == user_id),
        ]
        for model, scope in scopes:
            result = await session.execute(delete(model).where(scope))
            counts[model.__tablename__] = result.rowcount
    return counts


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--user-id", required=True)
    parser.add_argument("--workers-stopped", action="store_true")
    args = parser.parse_args()
    settings = Settings()
    validate_reset(settings.app_environment, args.workers_stopped, args.user_id)
    # Keep checkpoint cleanup and application cleanup atomic, rather than partial cross-DB reset.
    if settings.langgraph_checkpoint_database_url and (
        make_url(settings.langgraph_checkpoint_database_url).set(
            drivername="postgresql"
        )
        != make_url(settings.database_url).set(drivername="postgresql")
    ):
        raise ValueError(
            "Demo reset requires checkpoints in the same database as application state"
        )
    engine = create_async_engine(settings.database_url)
    try:
        counts = await reset_demo_state(
            async_sessionmaker(engine),
            environment=settings.app_environment,
            workers_stopped=args.workers_stopped,
            user_id=args.user_id,
        )
        print(f"Demo reset completed for {args.user_id}: {counts}")
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
