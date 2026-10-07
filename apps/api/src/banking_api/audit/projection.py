from datetime import UTC, datetime
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy import func, select

from banking_api.application.task_service import TaskNotFoundError
from banking_api.audit.models import (
    AuditActor,
    AuditEntry,
    AuditFact,
    AuditResource,
    AuditTrace,
    AuditWriteEvidence,
)
from banking_api.audit.safety import safe_text
from banking_api.domain.enums import OperationStatus, WorkflowStatus
from banking_api.domain.risk import TransferRiskDecision
from banking_api.persistence.models import (
    ApprovalModel,
    ConversationModel,
    EventModel,
    MockBankTransferModel,
    MockSubscriptionActionModel,
    MockSubscriptionCancellationModel,
    OperationModel,
    PlanModel,
    ReauthenticationModel,
    TaskModel,
    WorkflowModel,
)
from banking_api.persistence.repositories.plans import PlanRepository
from banking_api.planning.models import ConditionDecision

# No runtime message, raw tool payload, model answer or credential enters this projection.
LABELS = {
    "conversation.message.created": "用户请求已接收（原文见当前对话）",
    "task.created": "任务已创建",
    "task.started": "任务开始执行",
    "task.completed": "任务完成；写业务结果仍由 Workflow / Operation 决定",
    "task.failed": "任务失败",
    "request.routed": "请求已路由至注册执行者",
    "workflow.created": "创建业务草稿并保存提取意图",
    "workflow.waiting_for_input": "等待用户确认收款人或业务对象",
    "workflow.ready_for_review": "业务校验完成，等待用户确认",
    "workflow.updated": "业务信息更新",
    "workflow.ready_for_commit": "安全控制完成，可以提交",
    "workflow.reauth_required": "需要 Mock 强身份验证",
    "workflow.risk_evaluated": "后端风险评估",
    "workflow.risk_escalated": "风险升级，必须满足更严格控制",
    "workflow.committing": "正在提交；尚未确认业务成功",
    "workflow.succeeded": "Workflow 已成功（需同时确认 Operation）",
    "workflow.failed": "Workflow 失败",
    "workflow.cancelled": "用户取消工作流",
    "approval.created": "创建绑定 canonical payload 的确认",
    "approval.approved": "用户已确认当前 payload",
    "approval.invalidated": "业务内容变更，旧确认已失效",
    "approval.expired": "用户确认已过期",
    "approval.consumed": "确认已消费并绑定唯一 Operation",
    "reauth.challenge.created": "创建 Mock Reauthentication",
    "reauth.verified": "Mock 强验证通过；不代表业务成功",
    "reauth.failed": "Mock 强验证失败（不保存验证码）",
    "reauth.invalidated": "原 Mock 强验证已失效",
    "reauth.expired": "Mock 强验证已过期",
    "security.write_check": "Security Guard 新写操作检查",
    "security.reauth_failed": "Security Guard 记录验证失败",
    "security.control_bypass_attempt": "Security Guard 拒绝控制绕过",
    "security.write_lock_activated": "触发写操作临时锁定；查询与已有操作恢复仍允许",
    "operation.created": "创建唯一银行 Operation",
    "operation.reconcile_started": "对原 Operation 发起 reconcile / recovery",
    "provider.submit_started": "向 Mock Provider 提交原幂等身份",
    "operation.submitted": "Mock Provider 已接收，结果尚未最终确认",
    "operation.unknown": "Provider 结果 UNKNOWN；不显示成功",
    "operation.succeeded": "Mock Provider 最终确认成功",
    "operation.failed": "Mock Provider 确认失败",
    "plan.state_changed": "计划状态变化",
    "plan.step_state_changed": "计划步骤状态变化",
}
FACT_LABELS = {
    "route": "路由",
    "risk_level": "后端风险等级",
    "executor_id": "注册执行者",
    "requested_output": "输出类型",
    "version": "资源版本",
    "payload_hash": "完整 payload hash",
    "expires_at": "有效期至",
    "evaluated_at": "策略决策时间",
    "within_ttl": "查询时仍在有效期内（不代表动作已授权）",
    "created_at": "创建时间",
    "approved_at": "确认时间",
    "invalidated_at": "失效时间",
    "consumed_at": "消费时间",
    "verified_at": "验证时间",
    "method": "验证模式",
    "attempt_count": "失败尝试数",
    "user_id": "所属用户",
    "idempotency_key": "Provider 幂等身份",
    "provider_reference": "Provider reference",
    "error_code": "领域错误",
    "reason_code": "原因",
    "signal_type": "触发类型",
    "window_seconds": "窗口（秒）",
    "locked_at": "锁定时间",
    "locked_until": "锁定至",
    "status": "状态",
    "capability": "Capability",
    "step_kind": "步骤类型",
    "guard_condition_step_id": "Guard 来源",
    "depends_on": "依赖步骤",
    "required_approval": "需要用户确认",
    "required_reauthentication": "需要 Mock 强验证",
    "reconcile_attempts": "恢复次数",
    "provider_mode": "Provider 模式",
    "recipient_query": "收款人查询",
    "payee_id": "已解析收款人",
    "source_account_id": "已选择付款账户",
    "source_account_hint": "付款账户提示",
    "amount": "金额（Decimal）",
    "currency": "币种",
    "source_account_display_name": "付款账户",
    "source_account_masked_number": "账户尾号",
    "payee_display_name": "收款人",
    "payee_masked_account": "收款尾号",
    "validation_valid": "确定性校验通过",
    "validated_at": "校验时间",
    "validation_codes": "校验领域错误",
    "subscription_query": "订阅查询",
    "subscription_id": "订阅身份",
    "merchant": "商户",
    "management_type": "管理类型",
    "cancellable": "后端可取消能力",
    "final_subscription_status": "订阅最终状态",
    "approval_id": "关联确认",
    "workflow_id": "关联 Workflow",
}


def facts(values: dict) -> list[AuditFact]:
    return [
        AuditFact(key=key, label=FACT_LABELS[key], value=safe_text(value))
        for key, value in values.items()
        if key in FACT_LABELS and value is not None
    ][:40]


def _uuid(value) -> UUID | None:
    try:
        return UUID(str(value))
    except (ValueError, TypeError):
        return None


def _typed(model, data):
    try:
        return model.model_validate(
            {key: value for key, value in data.items() if key in model.model_fields}
        )
    except (ValidationError, TypeError, AttributeError):
        return None


class AuditProjection:
    def __init__(self, session):
        self.session = session

    async def get(self, task_id: UUID, user_id: str) -> AuditTrace:
        # Both task and parent ownership checked, before any related resource/event read.
        task = await self.session.scalar(
            select(TaskModel)
            .join(ConversationModel)
            .where(
                TaskModel.task_id == task_id,
                TaskModel.user_id == user_id,
                ConversationModel.user_id == user_id,
            )
        )
        if task is None:
            raise TaskNotFoundError
        events = list(
            (
                await self.session.scalars(
                    select(EventModel)
                    .where(
                        EventModel.task_id == task_id,
                        EventModel.conversation_id == task.conversation_id,
                    )
                    .order_by(EventModel.sequence)
                    .limit(1001)
                )
            ).all()
        )
        workflows = list(
            (
                await self.session.scalars(
                    select(WorkflowModel).where(
                        WorkflowModel.source_task_id == task_id,
                        WorkflowModel.user_id == user_id,
                    )
                )
            ).all()
        )
        workflow_ids = [w.workflow_id for w in workflows]
        approvals = list(
            (
                await self.session.scalars(
                    select(ApprovalModel)
                    .where(
                        ApprovalModel.workflow_id.in_(workflow_ids),
                        ApprovalModel.user_id == user_id,
                    )
                    .order_by(ApprovalModel.created_at)
                )
            ).all()
        )
        reauths = list(
            (
                await self.session.scalars(
                    select(ReauthenticationModel)
                    .where(
                        ReauthenticationModel.workflow_id.in_(workflow_ids),
                        ReauthenticationModel.user_id == user_id,
                    )
                    .order_by(ReauthenticationModel.created_at)
                )
            ).all()
        )
        operations = list(
            (
                await self.session.scalars(
                    select(OperationModel).where(
                        OperationModel.workflow_id.in_(workflow_ids),
                        OperationModel.user_id == user_id,
                    )
                )
            ).all()
        )
        resources = []
        for item in approvals:
            resources.append(
                AuditResource(
                    resource_type="APPROVAL",
                    resource_id=item.approval_id,
                    status=item.status.value,
                    facts=facts(
                        {
                            "user_id": user_id,
                            "workflow_id": item.workflow_id,
                            "created_at": item.created_at,
                            "expires_at": item.expires_at,
                            "within_ttl": (
                                item.expires_at.replace(tzinfo=UTC)
                                if item.expires_at.tzinfo is None
                                else item.expires_at
                            )
                            > datetime.now(UTC),
                            "approved_at": item.approved_at,
                            "invalidated_at": item.invalidated_at,
                            "consumed_at": item.consumed_at,
                            "payload_hash": item.payload_hash,
                            "amount": item.payload_json.get("amount"),
                            "currency": item.payload_json.get("currency"),
                            "source_account_id": item.payload_json.get("source_account_id"),
                            "payee_id": item.payload_json.get("payee_id"),
                            "subscription_id": item.payload_json.get("subscription_id"),
                        }
                    ),
                )
            )
        for item in reauths:
            resources.append(
                AuditResource(
                    resource_type="REAUTHENTICATION",
                    resource_id=item.reauth_id,
                    status=item.status.value,
                    facts=facts(
                        {
                            "method": "Mock Reauthentication",
                            "workflow_id": item.workflow_id,
                            "approval_id": item.approval_id,
                            "created_at": item.created_at,
                            "expires_at": item.expires_at,
                            "within_ttl": (
                                item.expires_at.replace(tzinfo=UTC)
                                if item.expires_at.tzinfo is None
                                else item.expires_at
                            )
                            > datetime.now(UTC),
                            "attempt_count": item.attempt_count,
                            "verified_at": item.verified_at,
                        }
                    ),
                )
            )
        for item in operations:
            resources.append(
                AuditResource(
                    resource_type="OPERATION",
                    resource_id=item.operation_id,
                    status=item.status.value,
                    facts=facts(
                        {
                            "workflow_id": item.workflow_id,
                            "approval_id": item.approval_id,
                            "idempotency_key": item.idempotency_key,
                            "payload_hash": item.payload_hash,
                            "created_at": item.created_at,
                            "provider_reference": item.provider_reference,
                            "error_code": item.error_code,
                            "reconcile_attempts": item.reconcile_attempts,
                            "provider_mode": "Mock",
                            "final_subscription_status": "CANCELLED"
                            if (
                                item.operation_type.value == "SUBSCRIPTION_CANCEL"
                                and item.status is OperationStatus.SUCCEEDED
                            )
                            else None,
                        }
                    ),
                )
            )
        plan = await self.session.scalar(
            select(PlanModel).where(
                PlanModel.source_task_id == task_id,
                PlanModel.user_id == user_id,
            )
        )
        skipped = []
        if plan:
            repo = PlanRepository(self.session)
            deps = await repo.dependencies(plan.plan_id)
            for step in await repo.steps(plan.plan_id):
                resources.append(
                    AuditResource(
                        resource_type="PLAN_STEP",
                        resource_id=step.step_id,
                        status=step.status,
                        facts=facts(
                            {
                                "capability": step.capability,
                                "step_kind": step.step_kind,
                                "depends_on": deps.get(step.step_id, []),
                                "guard_condition_step_id": step.guard_condition_step_id,
                            }
                        ),
                    )
                )
                if step.status == "SKIPPED" and step.capability in {
                    "TRANSFER_WORKFLOW",
                    "SUBSCRIPTION_CANCEL_WORKFLOW",
                    "SUBSCRIPTION_RESUME_WORKFLOW",
                }:
                    skipped.append(step.step_id)
        keys = [item.idempotency_key for item in operations]
        ledger_count = 0
        for model in (
            MockBankTransferModel,
            MockSubscriptionCancellationModel,
            MockSubscriptionActionModel,
        ):
            ledger_count += (
                await self.session.scalar(
                    select(func.count())
                    .select_from(model)
                    .where(
                        model.user_id == user_id,
                        model.idempotency_key.in_(keys),
                    )
                )
                or 0
            )
        entries = [entry for event in events[:1000] if (entry := self._entry(event, task_id))]
        return AuditTrace(
            trace_id=task_id,
            source_task_id=task_id,
            generated_at=datetime.now(UTC),
            task_status=task.status.value,
            entries=entries,
            resources=resources[:100],
            history_truncated=len(events) > 1000 or len(resources) > 100,
            history_note=(
                "时间线来自持久 Event；资源详情是当前快照。旧版本未记录的细节不会补造。"
                "原文见所属对话；不复制完整 Prompt 或模型推理。"
            ),
            write_evidence=AuditWriteEvidence(
                workflow_count=len(workflows),
                approval_count=len(approvals),
                operation_count=len(operations),
                provider_ledger_count=ledger_count,
                provider_submission_count=sum(
                    e.event_type == "provider.submit_started" for e in events
                ),
                skipped_write_step_ids=skipped,
                business_success=any(
                    w.status is WorkflowStatus.SUCCEEDED
                    and any(
                        op.workflow_id == w.workflow_id and op.status is OperationStatus.SUCCEEDED
                        for op in operations
                    )
                    for w in workflows
                ),
                no_write_started=not workflows and not operations and ledger_count == 0,
            ),
        )

    @staticmethod
    def _entry(event, task_id) -> AuditEntry | None:
        kind = event.event_type
        if kind not in LABELS:
            return None
        data = event.data_json
        related = {
            key: identifier
            for key in (
                "workflow_id",
                "operation_id",
                "approval_id",
                "reauth_id",
                "plan_id",
                "step_id",
                "message_id",
            )
            if (identifier := _uuid(data.get(key))) is not None
        }
        resource_type, resource_id = next(
            (
                (key.removesuffix("_id").upper(), related[key])
                for key in (
                    "reauth_id",
                    "approval_id",
                    "operation_id",
                    "step_id",
                    "plan_id",
                    "workflow_id",
                    "message_id",
                )
                if key in related
            ),
            ("TASK", task_id),
        )
        risk = _typed(TransferRiskDecision, data) if kind.startswith("workflow.risk_") else None
        condition = _typed(ConditionDecision, data.get("condition_decision"))
        evidence = data.get("evidence", {})
        values = {
            **{key: data[key] for key in FACT_LABELS if key in data},
            **{key: evidence[key] for key in FACT_LABELS if key in evidence},
        }
        if evidence.get("subscriptions"):
            item = evidence["subscriptions"][0]
            values.update(
                {
                    key: item.get(key)
                    for key in (
                        "merchant",
                        "management_type",
                        "cancellable",
                        "subscription_id",
                    )
                }
            )
        actor = (
            AuditActor.SECURITY_GUARD
            if kind.startswith("security.")
            else AuditActor.USER
            if kind == "operation.reconcile_started" and data.get("actor_type") == "USER"
            else AuditActor.RECOVERY_WORKER
            if kind == "operation.reconcile_started"
            else AuditActor.PROVIDER
            if kind.startswith("provider.")
            or kind
            in {
                "operation.succeeded",
                "operation.failed",
                "operation.unknown",
                "operation.submitted",
            }
            else AuditActor.USER
            if kind in {"conversation.message.created", "approval.approved"}
            else AuditActor.WORKFLOW
            if kind.startswith(("workflow.", "approval.", "reauth."))
            else AuditActor.SYSTEM
        )
        return AuditEntry(
            event_id=event.event_id,
            sequence=event.sequence,
            timestamp=event.created_at,
            category=kind.split(".")[0].upper(),
            event_type=kind,
            actor_type=actor,
            resource_type=resource_type,
            resource_id=resource_id,
            status=safe_text(data.get("status", data.get("to_status")))
            if (data.get("status") is not None or data.get("to_status") is not None)
            else None,
            decision_summary=LABELS[kind],
            related_resource_ids=related,
            facts=facts(values),
            risk_decision=risk,
            condition_decision=condition,
        )
