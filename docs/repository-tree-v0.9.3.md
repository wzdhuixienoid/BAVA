# AI Banking Agent v0.9.3 Repository Tree

版本：**0.9.3**。生成日期：**2026-10-07，Asia/Shanghai**。数据库 head：**0019**。

依据当前工作树的实际 `rg --files --hidden` 生成，包含新增未提交源码、测试和本版三个交付文档。没有复制旧版本目录树，也没有恢复工作树中已删除的旧文档。

本图展开应用、API-client、迁移、测试、脚本、基础设施及当前文档；省略依赖、缓存、构建产物、Git 内部、`.env`、其余历史版本文档和 `report/` 的其他既有资料。`report/README.md` 仅表示该既有目录存在，不属于本版新增实现。

配套：[实现报告](implementation-report-v0.9.3.md)、[测试结果](test-results-v0.9.3.md)。

## 1. 当前目录树

本次展开 **392 个文件**。

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
│   │   │   │   ├── 0017_plan_conditions.py
│   │   │   │   ├── 0018_banking_management.py
│   │   │   │   └── 0019_conversation_titles.py
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
│   │   │       │   │   ├── payees.py
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
│   │   │       ├── payees/
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
│   │   │       │   ├── answers.py
│   │   │       │   ├── contracts.py
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
│   │   │   ├── banking_test_helpers.py
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
│   │   │   ├── test_management_postgres.py
│   │   │   ├── test_management_repairs.py
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
│   │   │   ├── test_transfer_payee_shortcuts.py
│   │   │   ├── test_transfer_risk.py
│   │   │   └── test_transfer_workflow.py
│   │   ├── .dockerignore
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
│       │   ├── payees/
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
│       │   │   ├── subscription-prefill.ts
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
│       │       │   ├── PayeeSelector.tsx
│       │       │   └── TransferWorkflowCard.tsx
│       │       ├── ReauthenticationForm.tsx
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
│       ├── public/
│       │   └── .gitkeep
│       ├── tests/
│       │   ├── account-results.test.mjs
│       │   ├── audit-evidence.test.mjs
│       │   ├── conversation-timeline.test.mjs
│       │   ├── product-visualization.test.mjs
│       │   ├── subscription-prefill.test.mjs
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
│   ├── assets/
│   │   ├── banking-management-delete.png
│   │   ├── banking-management-local-ready.png
│   │   ├── banking-management-payee-answer.png
│   │   ├── banking-management-payee-shortcuts.png
│   │   ├── banking-management-resume.png
│   │   ├── reply-processing-preview.jpg
│   │   ├── reply-result-preview.jpg
│   │   └── web-workbench-ui-preview.jpg
│   ├── architecture-baseline-v0.1.md
│   ├── banking-management-repairs.md
│   ├── implementation-report-v0.9.3.md
│   ├── repository-tree-v0.9.3.md
│   └── test-results-v0.9.3.md
├── infra/
│   └── postgres/
│       └── README.md
├── packages/
│   └── api-client/
│       ├── src/
│       │   ├── index.ts
│       │   └── schema.d.ts
│       └── package.json
├── report/
│   └── README.md
├── scripts/
│   ├── demo_preflight.py
│   ├── generate_golden_financial_metrics.py
│   ├── generate_golden_monthly_report_core.py
│   ├── generate_mock_data.py
│   ├── reset_demo_state.py
│   ├── smoke_agent.py
│   ├── smoke_audit_product.py
│   ├── smoke_monthly_report_skill.py
│   ├── smoke_plan_conditions.py
│   ├── smoke_plan_product.py
│   ├── smoke_report_product.py
│   ├── smoke_report_stability.py
│   ├── smoke_routing.py
│   ├── smoke_security_product.py
│   ├── smoke_transfer_authorization.py
│   ├── smoke_transfer_draft.py
│   ├── smoke_transfer_operation.py
│   └── validate_mock_data.py
├── .dockerignore
├── .env.example
├── .gitignore
├── Makefile
├── README.md
├── docker-compose.yml
├── package.json
├── pnpm-lock.yaml
└── pnpm-workspace.yaml
```

## 2. 本版新增入口

| 路径 | 职责 |
| --- | --- |
| `apps/api/migrations/versions/0018_banking_management.py` | 删除标记、收款人、订阅状态／动作账本及恢复枚举迁移 |
| `apps/api/src/banking_api/api/routes/payees.py` | 收款人列表／搜索和明确确认保存 API |
| `apps/api/src/banking_api/payees/service.py` | fixture＋数据库统一查询、资料校验、用户隔离与去重 |
| `apps/api/src/banking_api/subscriptions/contracts.py` | 当前合同状态覆盖、历史取消兼容和账期日历计算 |
| `apps/api/src/banking_api/subscriptions/answers.py` | 订阅回答共用收尾和一次总览提示 |
| `apps/api/tests/test_management_repairs.py` | 风险、删除、收款人、订阅恢复及历史兼容回归 |
| `apps/api/tests/test_management_postgres.py` | 消息／删除竞争、跨 Provider 合同版本串行 |
| `apps/api/tests/test_transfer_payee_shortcuts.py` | 快捷选择、旧草稿恢复、删除拦截和旧授权失效 |
| `apps/api/tests/banking_test_helpers.py` | Mock 认证及历史黄色授权测试辅助 |
| `apps/web/app/payees/page.tsx` | 收款人管理、核对保存、返回原转账 |
| `apps/web/features/workflows/ReauthenticationForm.tsx` | 转账和订阅恢复共用验证表单 |
| `apps/web/features/workflows/transfer/PayeeSelector.tsx` | 已有／新增快捷入口、筛选和具体账户选择 |

## 3. 修改的主要边界

- `application/conversation_service.py`、Conversation repository、Conversations／Events routes：软删除、行锁和 SSE 生命周期。
- `application/workflow_service.py`、`operation_service.py`、`workflows/transfer/`：所有资金支出强验证、快捷选择和授权失效。
- `workflows/subscription_cancel/`、`subscriptions/provider.py`：取消／恢复共用确定性流程、版本控制、幂等状态和动作账本。
- `routing/`、`planning/`、Task／Plan 执行：只读收款人查询及订阅恢复 Capability。
- `persistence/models.py`、`audit/projection.py`、`scripts/reset_demo_state.py`：持久化、审计及 scoped reset 新数据。
- `apps/web/features/conversation/`、`features/results/`、工作流卡、`lib/api/` 和 SSE：正文去重、动作区分及删除清理。
- `packages/api-client/src/schema.d.ts`：由实际 FastAPI OpenAPI 生成的接口类型。
- 项目／Web／API-client package、API `pyproject.toml`／`uv.lock`／`__init__.py`、页面及 preflight：0.9.3 版本同步。
- `scripts/smoke_audit_product.py`：旧黄色转账示例适配 RED＋Mock 强验证；本版未重跑真实模型 smoke。

以上源码路径未写全前缀时，相对于 `apps/api/src/banking_api/`。目录树只描述文件存在及职责，测试通过范围见测试结果，不从目录存在推断验收通过。

## 账单分析与数据扩容补充

沿用当前目录，无新增运行时目录：`context/builder.py` 和 `runtime/langgraph/graph.py` 处理财务日期与预算；`financial/analytics_service.py` 支持月份和自然年；`features/reports/` 适配年度标题与同比。`generate_mock_data.py` 生成 1,207 笔历史，`validate_mock_data.py` 校验连续月份，`generate_golden_financial_metrics.py` 生成全月份和年度参考。`test_mock_data.py` 和 `test_financial_golden.py` 覆盖可重现性及独立参考。
