# 历史档案：Implementation Report v0.7.1

> 历史材料，保留原记录日期、版本和结论。旧风险规则、待办事项、测试数量与本地部署状态不代表 v0.10.3；当前说明见 [文档导航](../../README.md)。

执行日期：2026-09-28（Asia/Shanghai）

## 1. 为什么修改原有流程

v0.6.1 对所有转账都强制 Approval + Reauthentication，虽然安全，但无法表达赛题的动态分级：低风险自动、中风险确认、高风险强验证。v0.7.1 保留 Approval、Reauthentication 和 Operation 的独立边界，只把“是否需要强验证”改为确定性 RiskDecision 的结果。

## 2. GREEN / YELLOW / RED

- GREEN：纯查询能力，自动执行，不创建 Approval 或 Reauthentication。`PolicyService` 对 R1 read-only Tool 显式返回业务风险 GREEN。
- YELLOW：用户当日 outgoing transfer exposure 加本笔金额 `<= 1000.00 CNY`，需 Approval，不需 Reauthentication。
- RED：上述 projected total `> 1000.00 CNY`，需 Approval + Reauthentication。

Transfer 最低为 YELLOW。`1000.00` 是 YELLOW，`1000.01` 是 RED。金额全程使用 `Decimal`。

## 3. 日累计口径

累计维度是 `Principal.user_id` 在当前业务日的 outgoing transfer exposure，不是单账户限额。业务日使用 `BANKING_BUSINESS_TIMEZONE`，默认 `Asia/Shanghai`，然后转换成 UTC 边界查询持久化数据。

## 4. successful 与 in-flight exposure

`TransferRiskFactsService` 读取两类确定性事实：

- successful：Mock Provider ledger 中当日 `SUCCEEDED` 的金额；
- in-flight：Application Operation 中当日 `CREATED / SUBMITTED / UNKNOWN` 的金额。

`FAILED` Operation 和 Provider failed fact 都排除。如果 Provider ledger 已对同一 idempotency key 记录终态，该 Application Operation 不再计入 in-flight，避免已成功金额被重复计算。

`SUBMITTED / UNKNOWN` 必须计入，因为 Provider 可能已接收或已执行该转账；忽略它们会让新转账基于过低的 exposure 通过 YELLOW gate。

## 5. RiskPolicy 输入与输出

`TransferRiskPolicy` 是小型纯确定性组件。输入为 requested amount、currency、business date、successful total、in-flight exposure 和 evaluation time。输出 `TransferRiskDecision`，包含 level、required controls、reason codes、三类金额、projected total、threshold 和 evaluated time。它不接受 LLM 生成的 risk level 或 control flag。

## 6. 持久化与审计

当 Workflow 首次到达 `READY_FOR_REVIEW`时，完整 RiskDecision 以 typed JSON 保存在 Workflow state 中；Decimal 序列化为字符串。Workflow API 另外暴露 `risk_level` 和 `risk_decision`。风险评估与升级使用 `workflow.risk_evaluated` / `workflow.risk_escalated` 事件，并通过现有 Event + Outbox 在同一业务事务中持久化。事件只包含结构化决策事实和 reason code。

本版无需新增表或 Workflow 列：现有 `state_json` 已是当前 typed Workflow state 的持久化位置，Event 保留决策历史。

## 7. Workflow 状态变化

Approval 后续状态由后端 RiskDecision 决定：

- YELLOW：`READY_FOR_REVIEW -> Approval -> READY_FOR_COMMIT`；
- RED：`READY_FOR_REVIEW -> Approval -> REAUTH_REQUIRED -> Reauthentication -> READY_FOR_COMMIT`。

前端不计算风险。Payload 变更仍会使 Approval 和 Reauthentication 失效，同时清除旧决策并对新 payload 重新评估。

## 8. commit-time 重评估与升级

Operation 创建前必须重新读取 exposure 并评估风险。如 review 时是 YELLOW，commit 时变为 RED：

1. 不创建 Operation，不调用 Provider；
2. 将 Workflow 更新为 RED / `REAUTH_REQUIRED`；
3. 保留 canonical payload 未变的 Approval；
4. 要求新的有效 Reauthentication。

Approval 表示用户已确认该 canonical payload，所以 payload 未变时仍有效；Reauthentication 是 RED 新增的独立安全控制，必须补齐。

同一 Workflow 在 payload 不变时使用 `max(previous risk, fresh risk)`，不会因时间或并发状态变化自动降级。

## 9. 并发门槛保护

`OperationService.prepare_transfer` 在 PostgreSQL 事务开始时按 `user_id` 的 SHA-256 稳定映射获取 `pg_advisory_xact_lock`。锁内重读 successful + in-flight exposure、重评估、验证 Approval/Reauthentication、创建 Operation、消费 Approval、更新 Workflow 并写审计事件，然后提交。锁随事务自动释放。

Provider network I/O 发生在上述事务提交之后，不持有 user risk lock。该锁保护用户级日认证门槛；Mock Provider 的 account lock 保护账户余额，两者没有合并。

## 10. Prompt Injection

`TransferIntent` 仍使用 `extra="forbid"`，LLM 只能输出 recipient、amount、currency 和 source account hint。针对“5000 元当绿色、不要确认或验证”的 regression 首先拒绝了额外的 `risk_level` / `required_reauthentication` 字段，然后由 RiskPolicy 将 5000 元判定为 RED。

## 11. UI

Transfer Workflow Card 直接展示后端返回的黄/红等级、本笔金额、今日已成功、执行中 exposure、预计日累计、Approval 和强验证需求。Commit 升级时展示“今日累计变化，现在需要强验证”。React 中没有金额门槛判定。

## 12. 执行验证

- 风险 / Transfer 定向批次：28 passed。
- 完整 backend：226 passed, 21 skipped（PostgreSQL marker 未在该命令提供 URL）。
- PostgreSQL suite：22 passed，包含两个 600 元 Workflow 的真实并发 gate。
- Ruff：通过。
- OpenAPI client 已重新生成；Web lint、typecheck 和 production build 通过。

## 13. 本版限制与 v0.7.2

强验证仍是比赛沙箱的 `MockReauthenticationProvider`。本版没有 Fraud Engine、异常交易检测、真实 OTP/人脸/U 盾、通用 Rule Engine/DSL、机器学习风控或新的业务场景。v0.7.2 可在不改变本版安全边界的前提下增加新策略或真实 step-up provider，但本版不预先实现。
