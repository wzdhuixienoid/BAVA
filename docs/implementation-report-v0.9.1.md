# Implementation Report v0.9.1

交付日期：2026-10-02。版本主题：比赛产品体验与可视化。

## 1. 版本目标

将已有银行能力变成可以直接理解、核验和演示的产品。没有新增银行业务场景。继续遵守 Backend decides facts / Frontend renders facts / LLM explains facts。

## 2. Phase A 安全基线

Transfer Risk Policy 显式仅支持 CNY；非 CNY 返回 `TRANSFER_RISK_CURRENCY_UNSUPPORTED`，不套用原币 1000 阈值、不做 FX、不自动判 RED。Workflow 和 Operation 创建边界复用该策略。账户币种不匹配仍保留 `CURRENCY_MISMATCH`。

`AccountListResult` / `AccountBalanceResult` 经成功 Tool execution 收集到 `Task.output.account_results`，同样用于 Plan。金额为 Decimal / JSON string，余额为 fixture 减成功 Provider ledger debits；账户归属、masked number、服务器 as_of 和 balance_display 都来自后端。

## 3. 可视化实现

新增 `/dashboard`，并在工作台保留对话、过程和完成索引。对话中的账户、消费、订阅、异常、风险、流程和条件均读取结构化结果。说明可展开查看；没有从 Markdown 提取金额或推测 DAG。

## 4. Financial Dashboard

只读 `GET /api/v1/dashboard?month=2026-08` 调用已有 Financial Analytics 四项能力，并复用 Monthly Report core/formatter。展示月收入、支出、上月支出、绝对/百分比变化、分类金额/占比条和 Top transactions。没有第二套金融统计代码，也不扫描 raw transactions 在浏览器聚合。

对话 Financial Analysis 的已完成 summary/category 输出可形成 `Task.output.financial_display`；缺失工具结果不由前端补算。Dashboard 确定性取得四项完整分析结果。

## 5. Account authoritative facts

账户卡直接展示 display_name、account_type 中文标签、masked_number、currency、balance_display、as_of。即使 LLM 写“余额只有 1 元”，卡片仍读取结构化余额。查询后保存快照，刷新 Dashboard 或再次查询取得最新 ledger 后余额。

## 6. Subscription Dashboard

复用现有 Subscription service 的成本计算，补充每项 monthly/annual projected cost 及 display fields；按币种分组。显示管理类型、当前状态、最近扣费、涨价、续费时间与证据。取消入口依赖后端 cancellable 和 subscription_id，跳转工作台仅预填请求，不自动授权或提交。DETECTED_ONLY 无正常可执行取消入口。多选候选 DTO 同样携带现有 authoritative cancellable；历史 JSON 缺省为 false，不凭 subscription_id 推断可取消。

## 7. Anomaly Cards

使用生成的 API type；后端补充金额和 evidence_display。显示商户、金额/币种、交易时间、severity、rule、原因和基线/倍数/计数证据，以及分析区间。明确标注“异常提示 ≠ 已确认欺诈”。检测器与四个既有规则未变，不触发 Security Guard。

## 8. Risk visualization

RiskDetails 直接读取 RiskDecision.level、required_approval、required_reauthentication、本笔/成功/执行中/含本笔 exposure、threshold、business_date 及后端 display fields。浏览器没有 1000 门槛或金额比较。真实浏览器验证了本笔 600 元、当日已有 2000 元成功、含本笔 2600 元暴露时显示 RED。查询显示 GREEN，取消显示后端 YELLOW。

## 9. Transfer Workflow visualization

`Workflow.presentation` 是持久状态的只读 projection：解析、收款人、账户、金额校验、风险、Approval、条件 Reauthentication、提交、Provider、最终结果。没有新增或简化业务状态机。READY_FOR_REVIEW、REAUTH_REQUIRED、READY_FOR_COMMIT、COMMITTING、FAILED、CANCELLED 与 Operation UNKNOWN 均保持真实语义。

`business_success` 仅在 Workflow 和 Operation 同为 SUCCEEDED 时为 true。成功回执和完成索引依赖该事实；旧资源 fallback 也要求两个真实状态均成功。UNKNOWN 显示“结果确认中”，只能 reconcile 原 Operation。

## 10. Subscription Workflow visualization

沿用同一 Timeline 和中文状态组件，显示 YELLOW、Approval required、无需 Reauthentication。确认不等于取消；提交后必须经过 Operation / Provider 收敛，双 SUCCEEDED 后才显示取消回执。页面刷新从资源 API 恢复。

## 11. Planner / DAG visualization

PlanCard 在对话中直接显示真实 Plan、Step kind、Capability、状态、依赖箭头、Guard 和 linked Workflow。使用响应式纵向节点与依赖引用展示 DAG，没有图布局框架。人工接管、resume、只读安全 rollback 复用现有动作；没有 Planner risk bypass。

## 12. Condition visualization

ConditionCard 展示后端 predicate、actual_display、threshold_display、currency、outcome、source step 和 evaluated_at。formatter 仅格式化 Decimal，不重新判断 outcome。FALSE 的写步骤显示持久 SKIPPED；TRUE 明确不等于授权，后续仍走原 Workflow 和安全控制。不根据 assistant text 猜测资源是否创建。

## 13. 中文状态系统

集中 `lib/presentation/status.ts` 覆盖生成 schema 中的 Task / Plan / Step / Workflow / Operation / Approval / Reauthentication / Security / Subscription / Timeline 状态，以 label、description、tone、icon 展示。未知未来状态显示“状态待同步”。中文错误说明集中在 errors.ts，仅呈现领域拒绝，不参与动作授权。

## 14. Demo reset

`scripts/reset_demo_state.py` 只允许 development/test、明确 user-id 和 workers-stopped，拒绝有效 Task / Operation / Outbox lease。清理该用户 ledger、guard、Workflow/Approval/Reauthentication/Operation、Plan/Task/Report/Conversation/Message/Event/Outbox、所属 LangGraph Task/Plan attempt checkpoints。保留其他用户、identity mapping、表结构和所有 migration 元数据。

应用与 checkpoint 必须在同一数据库，清理在单一 transaction 中执行；不清数据库或 Docker volume。真实 CLI 重复执行已验证幂等，Plan / checkpoint 的 PostgreSQL 回归通过。全部浏览器验收后再次 reset，交付运行状态恢复初始余额与活跃订阅。

## 15. Backend changes

新增 typed Account / Dashboard / Workflow presentation；为 RiskDecision、ConditionDecision、Subscription、Anomaly 添加 display fields；Task / Plan 暴露账户及金融展示结果。服务读取、统计、权限、风险、approval hash、reauth TTL、guard、Provider、恢复、lease/fencing 仍沿用原路径。

浏览器验收曾发现提取器将中文单位“元”放入 currency，后端正确以 CURRENCY_MISMATCH 拒绝。仅补充意图提取字段说明：明确 ISO 币种、条件阈值与转账金额的区别；没有添加服务端自动归一化、FX 或放宽拒绝规则。

报告说明提示同时明确既有禁用字符及包含数字字形的常用措辞，缩短文字解释，避免重复系统数值。原 SkillExecutor 数字/evidence/category/account 校验与重试上限保持原样；没有新增 verifier、数字修正或失败报告 fallback。

## 16. Frontend changes

新增 Dashboard、SpendingDashboard、AccountResults、RiskDetails、WorkflowTimeline、ConditionCard、StatusBadge。更新 PlanCard、SubscriptionSummaryCard、AnomalyCard、Workflow cards / receipts、AssistantTurn 和完成索引。复用既有月报组件与三栏/移动端结构，没有增加图表依赖。

## 17. API / OpenAPI changes

新增 authenticated / owner-scoped GET Dashboard。既有 Task schema 的 account_results / financial_display、Workflow.presentation、SubscriptionCandidate.cancellable 和相关 display fields 已进入 OpenAPI，`packages/api-client/src/schema.d.ts` 从实际运行 API 生成。没有手工维护重复 API 类型，没有 reset 业务 API。

FastAPI、OpenAPI、Python package/uv.lock、workspace/web/client package、前端版本展示和 README 均为 0.9.1。Docker 从这些源码构建，运行 OpenAPI info.version 实测为 0.9.1。

## 18. Migration changes

Migration added: **no**。Alembic head: **0017**。复用现有 JSON persistence / DTO projection；没有数据库字段变化。`alembic upgrade head` 在隔离 test 数据库执行成功，Docker 启动亦执行既有 migration。历史 migration 未修改。

## 19. Security invariants

- CNY-only 在 deterministic policy，而非 fixture、前端、Prompt 或 Planner。
- USD 同币种账户请求 fail closed；拒绝不创建 Operation、不消费 Approval、不创建有效 Reauthentication、不调用转账 Provider、不写 ledger。
- LLM ≠ authority；Principal、风险、条件结果、授权与状态均由后端决定。
- Decimal/string 是金额事实；浏览器不重算余额、汇率、消费、风险或 Condition。
- Approval binding、expiry、mutation invalidation，Reauthentication TTL/attempt limit，WRITE_LOCKED gate 不变。
- UNKNOWN、SUBMITTED、COMMITTING、Task COMPLETED、Approval/reauth 成功均不表示业务成功。
- FALSE guarded Step SKIPPED，无 Workflow / Operation / Provider 写副作用。
- ownership、provider idempotency、concurrent balance protection、Task lease/fencing、Operation recovery、Outbox 回归通过。

## 20. 已知限制

仅 synthetic banking / Mock Provider / Mock Reauthentication。没有 FX、真实短信/人脸/U盾、真实银行、理财、卡片管理、RAG、MCP、Multi-Agent、长期记忆、Kafka、Redis、Celery、任意代码执行或通用 Rule Engine（均 NOT IMPLEMENTED，属于明确禁止 scope）。

Dashboard 是多次有界读取的 projection，不提供跨服务原子快照。历史 Task 保留查询时事实。对话分析可能未调用全部分析工具，空缺结果不由浏览器猜测。LLM 路由/意图/报告说明可能失败；既有报告 grounding 拒绝保留，无逐句 semantic entailment verifier。初次浏览器报告生成曾被既有验证拒绝，重新生成通过；详见测试结果。

Planner 仍最多 8 步、2 条件、一个写 Workflow；没有 ELSE、多写、动态重规划。EventBus 仍 process-local，资源 API 是恢复事实源。reset 要求停 worker 和同库 checkpoint，非生产运维清理工具。

## 21. Release conclusion

**READY**。后端、PostgreSQL、前端 lint/typecheck/tests/build、OpenAPI generation、Docker、report/plan product smoke、Demo reset 和 T1–T14 实际浏览器验收均通过。最终报告提示修正后的实际 smoke 通过，golden core 一致；修正前失败保留在 Test Results。版本文档只新增本报告、Repository Tree、Test Results 三项；README 当前交付文档仅列 v0.9.1，旧版本文档保持原样。

本次交付为当前工作区源码与本地 Docker 产品，不包含远端仓库 push、发行包上传或生产部署。测试的具体命令、计数、初次失败与环境注意事项见 [Test Results](test-results-v0.9.1.md)。

## 修改文件清单

此清单依据最终 git 工作区生成，包含此前 Phase A 未提交改动和本轮可视化交付；不代表修改过旧版本说明。

### Backend（33）

- `apps/api/src/banking_api/__init__.py`
- `apps/api/src/banking_api/agents/financial_analysis_agent.py`
- `apps/api/src/banking_api/agents/minimal_banking_agent.py`
- `apps/api/src/banking_api/api/router.py`
- `apps/api/src/banking_api/api/routes/dashboard.py`
- `apps/api/src/banking_api/application/account_results.py`
- `apps/api/src/banking_api/application/operation_service.py`
- `apps/api/src/banking_api/application/plan_execution_service.py`
- `apps/api/src/banking_api/application/workflow_projection.py`
- `apps/api/src/banking_api/application/workflow_service.py`
- `apps/api/src/banking_api/domain/account.py`
- `apps/api/src/banking_api/domain/dashboard.py`
- `apps/api/src/banking_api/domain/risk.py`
- `apps/api/src/banking_api/domain/task.py`
- `apps/api/src/banking_api/domain/workflow.py`
- `apps/api/src/banking_api/domain/workflow_presentation.py`
- `apps/api/src/banking_api/financial/anomaly_models.py`
- `apps/api/src/banking_api/main.py`
- `apps/api/src/banking_api/mock_bank/service.py`
- `apps/api/src/banking_api/planning/models.py`
- `apps/api/src/banking_api/runtime/manual_agent_runtime.py`
- `apps/api/src/banking_api/runtime/task_runner.py`
- `apps/api/src/banking_api/skills/monthly_spending_report.py`
- `apps/api/src/banking_api/subscriptions/models.py`
- `apps/api/src/banking_api/subscriptions/service.py`
- `apps/api/src/banking_api/tools/banking/get_balance.py`
- `apps/api/src/banking_api/tools/banking/list_accounts.py`
- `apps/api/src/banking_api/tools/models.py`
- `apps/api/src/banking_api/workflows/subscription_cancel/engine.py`
- `apps/api/src/banking_api/workflows/subscription_cancel/models.py`
- `apps/api/src/banking_api/workflows/transfer/engine.py`
- `apps/api/src/banking_api/workflows/transfer/intent_extractor.py`
- `apps/api/src/banking_api/workflows/transfer/risk.py`

### Frontend / generated client（30）

- `apps/web/app/dashboard/page.tsx`
- `apps/web/app/page.tsx`
- `apps/web/app/subscriptions/page.tsx`
- `apps/web/components/agent-ui/StatusBadge.tsx`
- `apps/web/components/agent-ui/TaskStatus.tsx`
- `apps/web/features/accounts/AccountResults.tsx`
- `apps/web/features/accounts/presentation.ts`
- `apps/web/features/anomalies/TransactionAnomalyCard.tsx`
- `apps/web/features/conversation/AssistantTurn.tsx`
- `apps/web/features/conversation/MessageComposer.tsx`
- `apps/web/features/conversation/ResponseProcess.tsx`
- `apps/web/features/conversation/timeline.ts`
- `apps/web/features/dashboard/SpendingDashboard.tsx`
- `apps/web/features/plans/ConditionCard.tsx`
- `apps/web/features/plans/PlanCard.tsx`
- `apps/web/features/reports/CategoryBreakdown.tsx`
- `apps/web/features/results/ResultsPanel.tsx`
- `apps/web/features/results/WorkflowReceipt.tsx`
- `apps/web/features/security/SecurityStatusBanner.tsx`
- `apps/web/features/subscriptions/SubscriptionSummaryCard.tsx`
- `apps/web/features/subscriptions/presentation.ts`
- `apps/web/features/tasks/TaskActivity.tsx`
- `apps/web/features/workflows/RiskDetails.tsx`
- `apps/web/features/workflows/WorkflowTimeline.tsx`
- `apps/web/features/workflows/subscriptions/SubscriptionCancellationCard.tsx`
- `apps/web/features/workflows/transfer/TransferWorkflowCard.tsx`
- `apps/web/lib/api/client.ts`
- `apps/web/lib/presentation/errors.ts`
- `apps/web/lib/presentation/status.ts`
- `packages/api-client/src/schema.d.ts`

### Tests（10）

- `apps/api/tests/test_agent_task_e2e.py`
- `apps/api/tests/test_authoritative_accounts.py`
- `apps/api/tests/test_demo_reset.py`
- `apps/api/tests/test_postgres_integration.py`
- `apps/api/tests/test_product_projections.py`
- `apps/api/tests/test_subscriptions.py`
- `apps/api/tests/test_transfer_currency_policy.py`
- `apps/web/tests/account-results.test.mjs`
- `apps/web/tests/product-visualization.test.mjs`
- `apps/web/tests/tsx-loader.mjs`

### Scripts（1）

- `scripts/reset_demo_state.py`

### Docs（4）

- `README.md`
- `docs/implementation-report-v0.9.1.md`
- `docs/repository-tree-v0.9.1.md`
- `docs/test-results-v0.9.1.md`

### Version metadata（5）

- `apps/api/pyproject.toml`
- `apps/api/uv.lock`
- `apps/web/package.json`
- `package.json`
- `packages/api-client/package.json`
