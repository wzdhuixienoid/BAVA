# Workflow

Workflow = deterministic business process with explicit state transitions.

High-risk financial operations must eventually execute through workflows, not directly through agents.

以上两句是冻结的 Workflow 定义：Workflow 是具有显式状态转换的确定性业务流程；未来高风险金融操作必须通过 Workflow 执行，不能由 Agent 直接执行。

04.3 已实现首个完整 Workflow：`TRANSFER`。收款人、账户、金额、币种与余额校验由确定性引擎负责，不使用 LangGraph。用户审批 canonical payload 并完成绑定该 Approval 的 step-up Reauthentication 后，可通过确定性 Action 创建持久化 Operation。

> `READY_FOR_REVIEW` 只代表当前 Draft 通过初步校验，不代表已经批准，也不保证执行时余额仍然充足。

> `READY_FOR_COMMIT` 只表示进入该状态时，当前 Draft 有有效的 payload-bound Approval 和绑定该 Approval 的 Reauthentication；它不代表资金已转出，也不是执行时的永久凭证。

> 只有 Provider 确认的 `Operation SUCCEEDED` 表示资金已转出。`SUBMITTED` 和 `UNKNOWN` 都必须保持 `COMMITTING`。

Workflow 可以以 `workflow:transfer` 调用三项 R1 读能力、`transfer.get_status` (R1) 和唯一写能力 `transfer.commit` (`R4_FINANCIAL_COMMIT`, `side_effect=true`)。Commit Tool 只接受 `operation_id`，并从持久化 Operation 加载 authoritative payload 和 idempotency key。任何 Agent/Skill 都无该权限，LLM 不参与 Approval、Reauthentication、Commit 或 Verification。


v0.11.0理财申购和赎回使用独立方向Workflow，共享确认、强验证、SecurityGuard和Operation机制。交易日、费用规则和测评证据绑定核对快照；修改、过期或跨截止点重新授权。Provider持久资金/份额占用及独立结算账本，OperationRecoveryWorker推进成交与到账。只有SETTLED才成功；普通资源GET不推进状态。
