# 历史档案：AI Banking Agent v0.9.2 Repository Tree

> 历史材料，保留原记录日期、版本和结论。旧风险规则、待办事项、测试数量与本地部署状态不代表 v0.10.3；当前说明见 [文档导航](../../README.md)。

生成日期：2026-10-05。依据本次最终工作树实际 `rg --files` 与 `git diff` / untracked inventory；未复制旧版本树。正式产品版本0.9.2，Release verdict：**READY**；真实LLM、完整Browser与最终reset/preflight门槛已通过。

## Actual repository

以下展开当前源码、migrations、tests、scripts与本轮三个交付文档。依赖目录、构建产物、缓存、Git内部和历史版本文档不展开；历史文档保留且未修改。

```text
banking-agent/
├── apps/
│   ├── api/
│   │   ├── migrations/
│   │   │   ├── versions/
│   │   │   │   ├── 0001_bootstrap.py
│   │   │   │   ├── 0002_agent_task_progress.py
│   │   │   │   ├── 0003_task_runtime_backend.py
│   │   │   │   ├── 0004_task_executor.py
│   │   │   │   ├── 0005_reports.py
│   │   │   │   ├── 0006_transfer_workflows.py
│   │   │   │   ├── 0007_transfer_approval_reauth.py
│   │   │   │   ├── 0008_transfer_operations.py
│   │   │   │   ├── 0009_operation_recovery.py
│   │   │   │   ├── 0010_provider_transfer_errors.py
│   │   │   │   ├── 0011_transactional_outbox.py
│   │   │   │   ├── 0012_durable_task_execution.py
│   │   │   │   ├── 0013_oidc_identity_and_task_owner.py
│   │   │   │   ├── 0014_subscription_cancellation.py
│   │   │   │   ├── 0015_security_guard.py
│   │   │   │   ├── 0016_plan_dag.py
│   │   │   │   └── 0017_plan_conditions.py
│   │   │   ├── env.py
│   │   │   └── script.py.mako
│   │   ├── src/
│   │   │   └── banking_api/
│   │   │       ├── agents/
│   │   │       │   ├── README.md
│   │   │       │   ├── __init__.py
│   │   │       │   ├── financial_analysis_agent.py
│   │   │       │   ├── minimal_banking_agent.py
│   │   │       │   ├── models.py
│   │   │       │   └── subscription_analysis_agent.py
│   │   │       ├── api/
│   │   │       │   ├── routes/
│   │   │       │   │   ├── __init__.py
│   │   │       │   │   ├── conversations.py
│   │   │       │   │   ├── dashboard.py
│   │   │       │   │   ├── demo.py
│   │   │       │   │   ├── events.py
│   │   │       │   │   ├── health.py
│   │   │       │   │   ├── operations.py
│   │   │       │   │   ├── plans.py
│   │   │       │   │   ├── reports.py
│   │   │       │   │   ├── security.py
│   │   │       │   │   ├── subscriptions.py
│   │   │       │   │   ├── tasks.py
│   │   │       │   │   └── workflows.py
│   │   │       │   ├── __init__.py
│   │   │       │   ├── dependencies.py
│   │   │       │   └── router.py
│   │   │       ├── application/
│   │   │       │   ├── __init__.py
│   │   │       │   ├── account_results.py
│   │   │       │   ├── conversation_service.py
│   │   │       │   ├── operation_recovery_policy.py
│   │   │       │   ├── operation_service.py
│   │   │       │   ├── outbox_publication_policy.py
│   │   │       │   ├── plan_execution_service.py
│   │   │       │   ├── plan_service.py
│   │   │       │   ├── plan_wake_service.py
│   │   │       │   ├── report_service.py
│   │   │       │   ├── task_execution_policy.py
│   │   │       │   ├── task_service.py
│   │   │       │   ├── transfer_risk_facts.py
│   │   │       │   ├── workflow_projection.py
│   │   │       │   └── workflow_service.py
│   │   │       ├── audit/
│   │   │       │   ├── README.md
│   │   │       │   ├── __init__.py
│   │   │       │   ├── models.py
│   │   │       │   ├── projection.py
│   │   │       │   └── safety.py
│   │   │       ├── config/
│   │   │       │   ├── __init__.py
│   │   │       │   ├── demo_time.py
│   │   │       │   └── settings.py
│   │   │       ├── context/
│   │   │       │   ├── __init__.py
│   │   │       │   └── builder.py
│   │   │       ├── domain/
│   │   │       │   ├── __init__.py
│   │   │       │   ├── account.py
│   │   │       │   ├── approval.py
│   │   │       │   ├── conversation.py
│   │   │       │   ├── dashboard.py
│   │   │       │   ├── enums.py
│   │   │       │   ├── event.py
│   │   │       │   ├── message.py
│   │   │       │   ├── operation.py
│   │   │       │   ├── plan.py
│   │   │       │   ├── principal.py
│   │   │       │   ├── reauthentication.py
│   │   │       │   ├── report.py
│   │   │       │   ├── risk.py
│   │   │       │   ├── task.py
│   │   │       │   ├── workflow.py
│   │   │       │   └── workflow_presentation.py
│   │   │       ├── financial/
│   │   │       │   ├── __init__.py
│   │   │       │   ├── analysis_snapshot.py
│   │   │       │   ├── analytics_service.py
│   │   │       │   ├── anomaly_detector.py
│   │   │       │   ├── anomaly_models.py
│   │   │       │   ├── errors.py
│   │   │       │   ├── models.py
│   │   │       │   ├── report_formatter.py
│   │   │       │   └── report_models.py
│   │   │       ├── knowledge/
│   │   │       │   └── README.md
│   │   │       ├── llm/
│   │   │       │   ├── __init__.py
│   │   │       │   ├── fake_provider.py
│   │   │       │   ├── models.py
│   │   │       │   ├── openai_compatible_provider.py
│   │   │       │   └── provider.py
│   │   │       ├── memory/
│   │   │       │   └── README.md
│   │   │       ├── mock_bank/
│   │   │       │   ├── data/
│   │   │       │   │   ├── accounts.json
│   │   │       │   │   ├── golden_financial_metrics.json
│   │   │       │   │   ├── golden_monthly_report_core.json
│   │   │       │   │   ├── payees.json
│   │   │       │   │   ├── subscriptions.json
│   │   │       │   │   └── transactions.json
│   │   │       │   ├── __init__.py
│   │   │       │   └── service.py
│   │   │       ├── persistence/
│   │   │       │   ├── repositories/
│   │   │       │   │   ├── __init__.py
│   │   │       │   │   ├── approvals.py
│   │   │       │   │   ├── conversations.py
│   │   │       │   │   ├── events.py
│   │   │       │   │   ├── identities.py
│   │   │       │   │   ├── messages.py
│   │   │       │   │   ├── operations.py
│   │   │       │   │   ├── outbox.py
│   │   │       │   │   ├── plans.py
│   │   │       │   │   ├── reauthentications.py
│   │   │       │   │   ├── reports.py
│   │   │       │   │   ├── tasks.py
│   │   │       │   │   └── workflows.py
│   │   │       │   ├── __init__.py
│   │   │       │   ├── database.py
│   │   │       │   └── models.py
│   │   │       ├── planning/
│   │   │       │   ├── __init__.py
│   │   │       │   ├── condition_evaluator.py
│   │   │       │   ├── constraints.py
│   │   │       │   ├── models.py
│   │   │       │   ├── planner.py
│   │   │       │   ├── registry.py
│   │   │       │   ├── threshold_grounding.py
│   │   │       │   └── validator.py
│   │   │       ├── policy/
│   │   │       │   ├── __init__.py
│   │   │       │   └── service.py
│   │   │       ├── registries/
│   │   │       │   ├── __init__.py
│   │   │       │   ├── agent_registry.py
│   │   │       │   ├── skill_registry.py
│   │   │       │   ├── tool_registry.py
│   │   │       │   └── workflow_registry.py
│   │   │       ├── routing/
│   │   │       │   ├── __init__.py
│   │   │       │   ├── models.py
│   │   │       │   └── request_router.py
│   │   │       ├── runtime/
│   │   │       │   ├── langgraph/
│   │   │       │   │   ├── __init__.py
│   │   │       │   │   ├── checkpoint.py
│   │   │       │   │   ├── graph.py
│   │   │       │   │   └── state.py
│   │   │       │   ├── __init__.py
│   │   │       │   ├── agent_runtime.py
│   │   │       │   ├── base.py
│   │   │       │   ├── event_bus.py
│   │   │       │   ├── event_publisher.py
│   │   │       │   ├── manual_agent_runtime.py
│   │   │       │   ├── operation_recovery_worker.py
│   │   │       │   ├── outbox_publisher.py
│   │   │       │   ├── runtime_factory.py
│   │   │       │   ├── task_execution_worker.py
│   │   │       │   ├── task_reconciliation.py
│   │   │       │   └── task_runner.py
│   │   │       ├── security/
│   │   │       │   ├── authentication/
│   │   │       │   │   ├── __init__.py
│   │   │       │   │   ├── jwks.py
│   │   │       │   │   ├── provision.py
│   │   │       │   │   └── service.py
│   │   │       │   ├── reauthentication/
│   │   │       │   │   ├── __init__.py
│   │   │       │   │   ├── mock_provider.py
│   │   │       │   │   └── provider.py
│   │   │       │   ├── __init__.py
│   │   │       │   └── guard.py
│   │   │       ├── skill_runtime/
│   │   │       │   ├── __init__.py
│   │   │       │   └── executor.py
│   │   │       ├── skills/
│   │   │       │   ├── README.md
│   │   │       │   ├── __init__.py
│   │   │       │   ├── models.py
│   │   │       │   └── monthly_spending_report.py
│   │   │       ├── subscriptions/
│   │   │       │   ├── __init__.py
│   │   │       │   ├── detector.py
│   │   │       │   ├── models.py
│   │   │       │   ├── provider.py
│   │   │       │   └── service.py
│   │   │       ├── tools/
│   │   │       │   ├── banking/
│   │   │       │   │   ├── __init__.py
│   │   │       │   │   ├── commit_transfer.py
│   │   │       │   │   ├── compare_spending_periods.py
│   │   │       │   │   ├── detect_anomalies.py
│   │   │       │   │   ├── get_balance.py
│   │   │       │   │   ├── get_category_breakdown.py
│   │   │       │   │   ├── get_spending_summary.py
│   │   │       │   │   ├── get_top_transactions.py
│   │   │       │   │   ├── get_transfer_status.py
│   │   │       │   │   ├── list_accounts.py
│   │   │       │   │   └── search_payees.py
│   │   │       │   ├── __init__.py
│   │   │       │   ├── executor.py
│   │   │       │   ├── models.py
│   │   │       │   └── subscriptions.py
│   │   │       ├── transfers/
│   │   │       │   ├── __init__.py
│   │   │       │   ├── mock_provider.py
│   │   │       │   └── provider.py
│   │   │       ├── workflows/
│   │   │       │   ├── subscription_cancel/
│   │   │       │   │   ├── __init__.py
│   │   │       │   │   ├── authorization.py
│   │   │       │   │   ├── engine.py
│   │   │       │   │   ├── intent_extractor.py
│   │   │       │   │   └── models.py
│   │   │       │   ├── transfer/
│   │   │       │   │   ├── __init__.py
│   │   │       │   │   ├── authorization.py
│   │   │       │   │   ├── currency.py
│   │   │       │   │   ├── engine.py
│   │   │       │   │   ├── intent_extractor.py
│   │   │       │   │   ├── models.py
│   │   │       │   │   ├── risk.py
│   │   │       │   │   └── validation.py
│   │   │       │   └── README.md
│   │   │       ├── __init__.py
│   │   │       └── main.py
│   │   ├── tests/
│   │   │   ├── conftest.py
│   │   │   ├── test_agent_runtime.py
│   │   │   ├── test_agent_task_e2e.py
│   │   │   ├── test_audit_evidence.py
│   │   │   ├── test_audit_postgres.py
│   │   │   ├── test_authentication.py
│   │   │   ├── test_authoritative_accounts.py
│   │   │   ├── test_condition_threshold_grounding.py
│   │   │   ├── test_conversations.py
│   │   │   ├── test_demo_currency_time.py
│   │   │   ├── test_demo_preflight.py
│   │   │   ├── test_demo_reset.py
│   │   │   ├── test_events.py
│   │   │   ├── test_financial_agent_grounding.py
│   │   │   ├── test_financial_analysis_agent.py
│   │   │   ├── test_financial_analytics.py
│   │   │   ├── test_financial_golden.py
│   │   │   ├── test_financial_tools.py
│   │   │   ├── test_health.py
│   │   │   ├── test_llm_provider.py
│   │   │   ├── test_mock_data.py
│   │   │   ├── test_monthly_report_grounding.py
│   │   │   ├── test_monthly_spending_report_skill.py
│   │   │   ├── test_operation_recovery.py
│   │   │   ├── test_outbox.py
│   │   │   ├── test_plan_conditions.py
│   │   │   ├── test_plan_conditions_postgres.py
│   │   │   ├── test_plan_postgres.py
│   │   │   ├── test_plans.py
│   │   │   ├── test_postgres_integration.py
│   │   │   ├── test_principal_isolation.py
│   │   │   ├── test_product_projections.py
│   │   │   ├── test_provider_concurrency.py
│   │   │   ├── test_report_stability_runner.py
│   │   │   ├── test_reports.py
│   │   │   ├── test_request_router.py
│   │   │   ├── test_routing_integration.py
│   │   │   ├── test_runtime_hardening.py
│   │   │   ├── test_runtime_parity.py
│   │   │   ├── test_security_adversarial.py
│   │   │   ├── test_security_guard.py
│   │   │   ├── test_subscriptions.py
│   │   │   ├── test_task_execution.py
│   │   │   ├── test_tasks.py
│   │   │   ├── test_tool_executor.py
│   │   │   ├── test_transaction_anomalies.py
│   │   │   ├── test_transfer_authorization.py
│   │   │   ├── test_transfer_currency_policy.py
│   │   │   ├── test_transfer_operations.py
│   │   │   ├── test_transfer_risk.py
│   │   │   └── test_transfer_workflow.py
│   │   ├── Dockerfile
│   │   ├── alembic.ini
│   │   ├── pyproject.toml
│   │   └── uv.lock
│   └── web/
│       ├── app/
│       │   ├── auth/
│       │   │   └── popup-callback/
│       │   │       └── page.tsx
│       │   ├── dashboard/
│       │   │   └── page.tsx
│       │   ├── reports/
│       │   │   ├── [reportId]/
│       │   │   │   └── page.tsx
│       │   │   └── page.tsx
│       │   ├── subscriptions/
│       │   │   └── page.tsx
│       │   ├── globals.css
│       │   ├── layout.tsx
│       │   └── page.tsx
│       ├── components/
│       │   ├── agent-ui/
│       │   │   ├── StatusBadge.tsx
│       │   │   └── TaskStatus.tsx
│       │   └── auth/
│       │       └── AuthGate.tsx
│       ├── features/
│       │   ├── accounts/
│       │   │   ├── AccountResults.tsx
│       │   │   └── presentation.ts
│       │   ├── anomalies/
│       │   │   └── TransactionAnomalyCard.tsx
│       │   ├── audit/
│       │   │   ├── AuditPanel.tsx
│       │   │   └── AuditTimeline.tsx
│       │   ├── conversation/
│       │   │   ├── AssistantTurn.tsx
│       │   │   ├── ConversationPanel.tsx
│       │   │   ├── MarkdownMessage.tsx
│       │   │   ├── MessageComposer.tsx
│       │   │   ├── MessageList.tsx
│       │   │   ├── ResponseProcess.tsx
│       │   │   └── timeline.ts
│       │   ├── dashboard/
│       │   │   └── SpendingDashboard.tsx
│       │   ├── plans/
│       │   │   ├── ConditionCard.tsx
│       │   │   └── PlanCard.tsx
│       │   ├── reports/
│       │   │   ├── CategoryBreakdown.tsx
│       │   │   ├── MonthlyReportView.tsx
│       │   │   ├── PeriodComparison.tsx
│       │   │   ├── ReportCard.tsx
│       │   │   ├── ReportInsights.tsx
│       │   │   ├── ReportList.tsx
│       │   │   ├── ReportOverview.tsx
│       │   │   ├── TopTransactions.tsx
│       │   │   └── presentation.ts
│       │   ├── results/
│       │   │   ├── ResultsPanel.tsx
│       │   │   └── WorkflowReceipt.tsx
│       │   ├── security/
│       │   │   └── SecurityStatusBanner.tsx
│       │   ├── subscriptions/
│       │   │   ├── SubscriptionSummaryCard.tsx
│       │   │   └── presentation.ts
│       │   ├── tasks/
│       │   │   └── TaskActivity.tsx
│       │   └── workflows/
│       │       ├── subscriptions/
│       │       │   └── SubscriptionCancellationCard.tsx
│       │       ├── transfer/
│       │       │   └── TransferWorkflowCard.tsx
│       │       ├── RiskDetails.tsx
│       │       └── WorkflowTimeline.tsx
│       ├── lib/
│       │   ├── api/
│       │   │   └── client.ts
│       │   ├── auth/
│       │   │   └── AuthProvider.tsx
│       │   ├── events/
│       │   │   └── sse.ts
│       │   └── presentation/
│       │       ├── errors.ts
│       │       └── status.ts
│       ├── tests/
│       │   ├── account-results.test.mjs
│       │   ├── audit-evidence.test.mjs
│       │   ├── conversation-timeline.test.mjs
│       │   ├── product-visualization.test.mjs
│       │   └── tsx-loader.mjs
│       ├── Dockerfile
│       ├── eslint.config.mjs
│       ├── next-env.d.ts
│       ├── next.config.ts
│       ├── package.json
│       ├── postcss.config.mjs
│       ├── tailwind.config.ts
│       └── tsconfig.json
├── docs/
│   ├── implementation-report-v0.9.2.md
│   ├── repository-tree-v0.9.2.md
│   └── test-results-v0.9.2.md
├── packages/
│   └── api-client/
│       ├── src/
│       │   ├── index.ts
│       │   └── schema.d.ts
│       └── package.json
└── scripts/
    ├── demo_preflight.py
    ├── generate_golden_financial_metrics.py
    ├── generate_golden_monthly_report_core.py
    ├── generate_mock_data.py
    ├── reset_demo_state.py
    ├── smoke_agent.py
    ├── smoke_audit_product.py
    ├── smoke_monthly_report_skill.py
    ├── smoke_plan_conditions.py
    ├── smoke_plan_product.py
    ├── smoke_report_product.py
    ├── smoke_report_stability.py
    ├── smoke_routing.py
    ├── smoke_security_product.py
    ├── smoke_transfer_authorization.py
    ├── smoke_transfer_draft.py
    ├── smoke_transfer_operation.py
    └── validate_mock_data.py
```

根目录另有 README.md、package.json、pnpm-lock.yaml、pnpm-workspace.yaml、docker-compose.yml、.env.example 等实际配置。

## 本版本重要文件职责

| File | Responsibility |
|---|---|
| `apps/api/src/banking_api/audit/models.py` | Bounded Audit DTO；typed Risk/Condition 与 current snapshot 分离。 |
| `apps/api/src/banking_api/audit/projection.py` | 双 ownership 验证、持久 Event 顺序、资源/ledger 查询及 zero-write/business-success authoritative projection。 |
| `apps/api/src/banking_api/audit/safety.py` | 显式事实字段白名单、敏感文本排除、最小 Workflow resolver/validation evidence。 |
| `apps/api/src/banking_api/api/routes/tasks.py` | 新增只读 GET Task Audit；其他用户与不存在资源统一404。 |
| `apps/api/src/banking_api/api/routes/demo.py` | dev/test-only authenticated readiness；没有 reset 业务API。 |
| `apps/api/src/banking_api/application/workflow_service.py` | 授权历史与有限 resolver evidence、owner Guard context。 |
| `apps/api/src/banking_api/application/operation_service.py` | 消费授权、commit-time risk、Provider submit intent/reconcile/result evidence；原锁和fence保留。 |
| `apps/api/src/banking_api/security/guard.py` | NORMAL/WRITE_LOCKED 检查与拒绝事实、trigger/window/lock evidence。 |
| `apps/api/src/banking_api/workflows/transfer/currency.py` | 原始用户请求 grounded CNY aliases；未知/外币不盲目变CNY。 |
| `apps/api/src/banking_api/config/demo_time.py` | 仅只读 synthetic analysis reference time；安全TTL不使用。 |
| `apps/web/features/audit/AuditPanel.tsx` | Task入口、读取/refetch/cancel、404清除旧trace。 |
| `apps/web/features/audit/AuditTimeline.tsx` | 按backend顺序渲染历史/技术事实/当前资源；Mock与UNKNOWN明确。 |
| `packages/api-client/src/schema.d.ts` | 由实际 FastAPI OpenAPI 自动生成；无手写重复 API TS type。 |
| `scripts/demo_preflight.py` | localhost-only只读检查、版本/head/fixture/Guard/Mock配置，隐去credential。 |
| `scripts/reset_demo_state.py` | 原有owner-scoped dev/test reset复用，不改语义或migration/checkpoint schema。 |
| `scripts/smoke_audit_product.py` | 真实HTTP YELLOW授权/Operation/Provider/audit链及无secret检查；实际 PASS。 |
| `scripts/smoke_security_product.py` | 真实HTTP injection+直接commit拒绝/zero-write；实际 PASS。 |
| `scripts/smoke_report_stability.py` | isolated test DB串行≥10次真实report；Golden/validator/transport failures计数，未放宽校验。 |
| `apps/api/tests/test_audit_evidence.py` | 排序、owner、hash变更、风险升级、reauth/Guard、UNKNOWN/reconcile、Condition、subscription evidence。 |
| `apps/api/tests/test_audit_postgres.py` | 真实PostgreSQL UNKNOWN历史与最终Provider结果。 |
| `apps/api/tests/test_security_adversarial.py` | 8类Prompt injection、least privilege与Action API bypass。 |
| `apps/api/tests/test_demo_currency_time.py` | 6种CNY alias的Workflow/真实Plan路径、未知/外币、production时钟拒绝。 |
| `apps/api/tests/test_demo_preflight.py` | 真实ASGI readiness只读、逐项fail closed、production/remote URL拒绝。 |
| `apps/api/tests/test_report_stability_runner.py` | 逐次Golden/validator/transport分类与非零退出、production拒绝。 |
| `apps/web/tests/audit-evidence.test.mjs` | backend顺序、双风险、UNKNOWN、FALSE/zero-write、Mock、secret、404、prose mismatch行为测试。 |

## 本轮修改文件清单

包含新增及修改文件；以当前工作树为准，已完成产品版本验收，尚未创建Git提交、tag或推送。

- `.env.example`
- `README.md`
- `apps/api/pyproject.toml`
- `apps/api/src/banking_api/__init__.py`
- `apps/api/src/banking_api/api/router.py`
- `apps/api/src/banking_api/api/routes/dashboard.py`
- `apps/api/src/banking_api/api/routes/demo.py`
- `apps/api/src/banking_api/api/routes/tasks.py`
- `apps/api/src/banking_api/application/operation_service.py`
- `apps/api/src/banking_api/application/workflow_service.py`
- `apps/api/src/banking_api/audit/__init__.py`
- `apps/api/src/banking_api/audit/models.py`
- `apps/api/src/banking_api/audit/projection.py`
- `apps/api/src/banking_api/audit/safety.py`
- `apps/api/src/banking_api/config/demo_time.py`
- `apps/api/src/banking_api/config/settings.py`
- `apps/api/src/banking_api/domain/risk.py`
- `apps/api/src/banking_api/security/guard.py`
- `apps/api/src/banking_api/subscriptions/service.py`
- `apps/api/src/banking_api/tools/banking/detect_anomalies.py`
- `apps/api/src/banking_api/workflows/transfer/currency.py`
- `apps/api/src/banking_api/workflows/transfer/intent_extractor.py`
- `apps/api/tests/test_audit_evidence.py`
- `apps/api/tests/test_audit_postgres.py`
- `apps/api/tests/test_demo_currency_time.py`
- `apps/api/tests/test_demo_preflight.py`
- `apps/api/tests/test_postgres_integration.py`
- `apps/api/tests/test_report_stability_runner.py`
- `apps/api/tests/test_security_adversarial.py`
- `apps/api/uv.lock`
- `apps/web/app/dashboard/page.tsx`
- `apps/web/app/page.tsx`
- `apps/web/features/audit/AuditPanel.tsx`
- `apps/web/features/audit/AuditTimeline.tsx`
- `apps/web/features/conversation/AssistantTurn.tsx`
- `apps/web/lib/api/client.ts`
- `apps/web/package.json`
- `apps/web/tests/audit-evidence.test.mjs`
- `docker-compose.yml`
- `docs/archive/versions/implementation-report-v0.9.2.md`
- `docs/archive/versions/repository-tree-v0.9.2.md`
- `docs/archive/versions/test-results-v0.9.2.md`
- `package.json`
- `packages/api-client/package.json`
- `packages/api-client/src/schema.d.ts`
- `scripts/demo_preflight.py`
- `scripts/smoke_audit_product.py`
- `scripts/smoke_report_stability.py`
- `scripts/smoke_security_product.py`

## Migration

Migration added：no。现有 migrations/versions/0001—0017 全部保留；head：0017。无新 audit table，以 Event/Outbox + owner resource projection 实现。没有修改历史migration。

## Version documents

本轮只新增 implementation-report-v0.9.2.md、repository-tree-v0.9.2.md、test-results-v0.9.2.md；安全自评/Threat Model/Audit design集中在implementation report，真实测试和Security Evidence Matrix集中在test results。
