# Workflow

Workflow = deterministic business process with explicit state transitions.

High-risk financial operations must eventually execute through workflows, not directly through agents.

以上两句是冻结的 Workflow 定义：Workflow 是具有显式状态转换的确定性业务流程；未来高风险金融操作必须通过 Workflow 执行，不能由 Agent 直接执行。

04.1 已实现首个具体 Workflow：`TRANSFER`。它只能创建和校验转账草稿，最远到达
`READY_FOR_REVIEW`。收款人、账户、金额、币种与余额校验由确定性引擎负责，不使用 LangGraph。

> `READY_FOR_REVIEW` 只代表当前 Draft 通过初步校验，不代表已经批准，也不保证执行时余额仍然充足。

当前 Tool Registry 没有 transfer write capability，Workflow 仅允许以 `workflow:transfer`
调用 `payee.search`、`account.list` 和 `account.get_balance`；全部为
`R1_PRIVATE_READ` 且 `side_effect=false`。未实现 Approval、Reauthentication、OTP、
Operation、扣款、余额冻结或任何 mock execution。未来 commit 前必须重新校验
Policy、Balance、Payee 和 Payload。
