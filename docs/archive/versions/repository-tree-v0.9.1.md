# 历史档案：Repository Tree v0.9.1

> 历史材料，保留原记录日期、版本和结论。旧风险规则、待办事项、测试数量与本地部署状态不代表 v0.10.3；当前说明见 [文档导航](../../README.md)。

依据 2026-10-02 最终工作区实际文件生成。省略 node_modules、.venv、.next、缓存及历史版本文档的逐项展开。`[新增]` 包括本 release 内已完成的 Phase A 文件。

```text
banking-agent/
├── README.md                         当前能力、交付入口、Demo reset 与限制
├── package.json                      workspace 版本 0.9.1 与验证脚本
├── pnpm-workspace.yaml / pnpm-lock.yaml
├── docker-compose.yml                PostgreSQL、API、Web 本地产品
├── .env.example                      显式环境、认证与 Mock 配置
├── apps/
│   ├── api/
│   │   ├── Dockerfile
│   │   ├── pyproject.toml / uv.lock   Python package 0.9.1
│   │   ├── alembic.ini
│   │   ├── migrations/
│   │   │   ├── env.py
│   │   │   └── versions/             0001–0017；无新增/历史修改
│   │   ├── src/banking_api/
│   │   │   ├── __init__.py / main.py  FastAPI 版本与既有 runtime startup
│   │   │   ├── api/
│   │   │   │   ├── dependencies.py   Principal authentication / service wiring
│   │   │   │   ├── router.py
│   │   │   │   └── routes/
│   │   │   │       ├── dashboard.py  [新增] owner-scoped 只读金融总览 projection
│   │   │   │       ├── conversations.py / tasks.py / events.py
│   │   │   │       ├── workflows.py / operations.py / plans.py
│   │   │   │       └── reports.py / subscriptions.py / security.py / health.py
│   │   │   ├── application/
│   │   │   │   ├── account_results.py     [新增] 收集成功账户 Tool 的 typed facts
│   │   │   │   ├── workflow_projection.py [新增] 已有 Workflow 状态的只读时间线
│   │   │   │   ├── workflow_service.py / operation_service.py
│   │   │   │   ├── plan_execution_service.py / plan_service.py / plan_wake_service.py
│   │   │   │   ├── transfer_risk_facts.py  日暴露 authoritative facts
│   │   │   │   └── conversation/task/report service 与专用 recovery policies
│   │   │   ├── domain/
│   │   │   │   ├── account.py              [新增] 有界 AccountList/BalanceResult
│   │   │   │   ├── dashboard.py            [新增] typed DashboardSnapshot
│   │   │   │   ├── workflow_presentation.py [新增] typed 展示阶段/账户选项
│   │   │   │   ├── risk.py                 RiskDecision 与后端 display fields
│   │   │   │   ├── task.py / workflow.py   typed output / projection
│   │   │   │   └── enums.py 与其余既有资源 DTO
│   │   │   ├── agents/                    minimal / financial / subscription agents
│   │   │   ├── tools/                     registry-bound financial/account/subscription tools
│   │   │   ├── workflows/
│   │   │   │   ├── transfer/              intent、validation、CNY-only risk、authorization、engine
│   │   │   │   └── subscription_cancel/   原 YELLOW 取消流程；候选携带后端 cancellable
│   │   │   ├── financial/
│   │   │   │   ├── analytics_service.py   既有 Decimal 汇总/分类/比较/排名
│   │   │   │   ├── report_formatter.py / report_models.py
│   │   │   │   ├── analysis_snapshot.py
│   │   │   │   └── anomaly_detector.py / anomaly_models.py  规则与 evidence display
│   │   │   ├── subscriptions/             detector/service/model/provider，成本 display
│   │   │   ├── planning/                  constrained planner、validator、grounding、Condition
│   │   │   ├── security/                  OIDC、Security Guard、Mock Reauthentication
│   │   │   ├── transfers/                 Mock Provider 与故障注入模式
│   │   │   ├── persistence/               models、repositories、PostgreSQL session
│   │   │   ├── runtime/                   Task/Operation/Outbox loops、LangGraph checkpoint
│   │   │   ├── routing/ / policy/ / registries/
│   │   │   ├── skills/ / skill_runtime/    既有月度报告 Skill
│   │   │   ├── mock_bank/data/             committed synthetic accounts/payees/transactions/subscriptions/golden
│   │   │   ├── llm/ / context/ / config/
│   │   │   └── audit/ / knowledge/ / memory/  既有说明占位，未新增相关功能
│   │   └── tests/
│   │       ├── test_authoritative_accounts.py    [新增] 错误 LLM prose / ledger / ownership
│   │       ├── test_transfer_currency_policy.py  [新增] CNY / USD 同币种 fail closed / Plan
│   │       ├── test_product_projections.py       [新增] Dashboard、pending Workflow、Condition 仅格式化
│   │       ├── test_demo_reset.py                [新增] 环境拒绝、lease、隔离、幂等、PG checkpoints
│   │       ├── test_agent_task_e2e.py / test_postgres_integration.py  补充账户事实断言
│   │       ├── test_transfer_* / test_operation_recovery.py / test_provider_concurrency.py
│   │       ├── test_plan* / test_condition_threshold_grounding.py
│   │       └── 既有 financial、report、subscription、anomaly、auth、guard、task、outbox suites
│   └── web/
│       ├── Dockerfile / package.json            Next.js 产品与版本 0.9.1
│       ├── app/
│       │   ├── page.tsx                        对话三栏/移动页与 Dashboard 入口
│       │   ├── dashboard/page.tsx              [新增] typed 总览，只传月份/刷新请求
│       │   ├── subscriptions/page.tsx          订阅成本和当前状态
│       │   ├── reports/page.tsx / reports/[reportId]/page.tsx
│       │   └── auth/popup-callback/ / layout.tsx / globals.css
│       ├── components/
│       │   ├── agent-ui/StatusBadge.tsx         [新增] 统一中文状态组件
│       │   ├── agent-ui/TaskStatus.tsx
│       │   └── auth/AuthGate.tsx
│       ├── features/
│       │   ├── accounts/AccountResults.tsx / presentation.ts [新增] 权威账户/余额卡
│       │   ├── dashboard/SpendingDashboard.tsx  [新增] 复用月报可视化组件
│       │   ├── plans/ConditionCard.tsx          [新增] 后端 TRUE/FALSE 与事实展示
│       │   ├── plans/PlanCard.tsx               真实 DAG/依赖/Guard/动作
│       │   ├── workflows/RiskDetails.tsx        [新增] 后端 RiskDecision，含 exposure
│       │   ├── workflows/WorkflowTimeline.tsx  [新增] 后端 presentation stages
│       │   ├── workflows/transfer/TransferWorkflowCard.tsx
│       │   ├── workflows/subscriptions/SubscriptionCancellationCard.tsx
│       │   ├── conversation/                   AssistantTurn、过程、消息、输入、timeline
│       │   ├── results/                        双成功回执与完成索引
│       │   ├── reports/                        指标、环比、分类条、Top list、报告说明
│       │   ├── subscriptions/                  capability-bound 取消入口与成本卡
│       │   ├── anomalies/TransactionAnomalyCard.tsx
│       │   ├── security/SecurityStatusBanner.tsx
│       │   └── tasks/TaskActivity.tsx
│       ├── lib/
│       │   ├── presentation/status.ts / errors.ts [新增] 展示映射，不负责业务决策
│       │   ├── api/client.ts                   generated schema + authenticated Domain API
│       │   ├── events/sse.ts
│       │   └── auth/AuthProvider.tsx
│       └── tests/
│           ├── account-results.test.mjs         [新增] 后端余额与错误 prose 的真实组件
│           ├── product-visualization.test.mjs    [新增] 风险/条件/UNKNOWN/索引/取消/状态
│           ├── tsx-loader.mjs                   [新增] 使用现有 TypeScript 测试 TSX
│           └── conversation-timeline.test.mjs   既有回复关联、恢复、双成功语义
├── packages/api-client/
│   ├── package.json                            client metadata 0.9.1
│   └── src/index.ts / schema.d.ts               OpenAPI 生成的唯一 API type source
├── scripts/
│   ├── reset_demo_state.py                     [新增] 明确用户范围的 dev/test-only reset
│   ├── smoke_report_product.py / smoke_plan_product.py
│   ├── smoke_plan_conditions.py
│   ├── smoke_transfer_draft.py / smoke_transfer_authorization.py / smoke_transfer_operation.py
│   ├── smoke_agent.py / smoke_routing.py / smoke_monthly_report_skill.py
│   └── generate_mock_data.py / validate_mock_data.py / generate_golden_*.py
└── docs/
    ├── implementation-report-v0.9.1.md          [新增] 实际实现、文件清单与发布结论
    ├── repository-tree-v0.9.1.md                [新增] 本次真实仓库职责树
    ├── test-results-v0.9.1.md                   [新增] 真实命令、计数、浏览器与安全证据
    └── 既有 baseline、v0.1–v0.8.2 与 UI 历史说明/资产（保持原样）
```

`migrations` 实际位于 `apps/api/migrations`，Backend tests 位于 `apps/api/tests`，Frontend tests 位于 `apps/web/tests`；没有新增顶层数据库迁移或测试框架目录。
