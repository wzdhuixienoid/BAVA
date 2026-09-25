from typing import Any
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from banking_api.domain.enums import WorkflowStatus
from banking_api.domain.workflow import WorkflowType
from banking_api.persistence.models import WorkflowModel, utc_now


class WorkflowRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(
        self,
        *,
        user_id: str,
        conversation_id: UUID,
        source_task_id: UUID,
        workflow_type: WorkflowType,
        status: WorkflowStatus,
        state: dict[str, Any],
    ) -> WorkflowModel:
        model = WorkflowModel(
            user_id=user_id,
            conversation_id=conversation_id,
            source_task_id=source_task_id,
            workflow_type=workflow_type,
            status=status,
            state_json=state,
            version=1,
        )
        self.session.add(model)
        await self.session.flush()
        return model

    async def get_for_user(self, workflow_id: UUID, user_id: str) -> WorkflowModel | None:
        result = await self.session.execute(
            select(WorkflowModel).where(
                WorkflowModel.workflow_id == workflow_id,
                WorkflowModel.user_id == user_id,
            )
        )
        return result.scalar_one_or_none()

    async def get_for_user_for_update(
        self, workflow_id: UUID, user_id: str
    ) -> WorkflowModel | None:
        result = await self.session.execute(
            select(WorkflowModel)
            .where(
                WorkflowModel.workflow_id == workflow_id,
                WorkflowModel.user_id == user_id,
            )
            .with_for_update()
        )
        return result.scalar_one_or_none()

    async def list_for_user(
        self, user_id: str, conversation_id: UUID | None = None
    ) -> list[WorkflowModel]:
        statement = select(WorkflowModel).where(WorkflowModel.user_id == user_id)
        if conversation_id is not None:
            statement = statement.where(WorkflowModel.conversation_id == conversation_id)
        result = await self.session.execute(statement.order_by(WorkflowModel.created_at.desc()))
        return list(result.scalars())

    async def update_if_version(
        self,
        *,
        workflow_id: UUID,
        user_id: str,
        expected_version: int,
        status: WorkflowStatus,
        state: dict[str, Any],
    ) -> WorkflowModel | None:
        result = await self.session.execute(
            update(WorkflowModel)
            .where(
                WorkflowModel.workflow_id == workflow_id,
                WorkflowModel.user_id == user_id,
                WorkflowModel.version == expected_version,
            )
            .values(
                status=status,
                state_json=state,
                version=WorkflowModel.version + 1,
                updated_at=utc_now(),
            )
            .returning(WorkflowModel)
        )
        return result.scalar_one_or_none()
