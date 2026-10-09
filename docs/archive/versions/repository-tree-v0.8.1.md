# 历史档案：v0.8.1 直接新增或修改文件

> 历史材料，保留原记录日期、版本和结论。旧风险规则、待办事项、测试数量与本地部署状态不代表 v0.10.3；当前说明见 [文档导航](../../README.md)。

```text
README.md
apps/api/migrations/versions/0016_plan_dag.py
apps/api/pyproject.toml
apps/api/src/banking_api/api/router.py
apps/api/src/banking_api/api/routes/plans.py
apps/api/src/banking_api/application/operation_service.py
apps/api/src/banking_api/application/plan_execution_service.py
apps/api/src/banking_api/application/plan_service.py
apps/api/src/banking_api/application/plan_wake_service.py
apps/api/src/banking_api/application/workflow_service.py
apps/api/src/banking_api/domain/plan.py
apps/api/src/banking_api/main.py
apps/api/src/banking_api/persistence/models.py
apps/api/src/banking_api/persistence/repositories/plans.py
apps/api/src/banking_api/planning/__init__.py
apps/api/src/banking_api/planning/constraints.py
apps/api/src/banking_api/planning/models.py
apps/api/src/banking_api/planning/planner.py
apps/api/src/banking_api/planning/registry.py
apps/api/src/banking_api/planning/validator.py
apps/api/src/banking_api/routing/models.py
apps/api/src/banking_api/routing/request_router.py
apps/api/src/banking_api/runtime/event_publisher.py
apps/api/src/banking_api/runtime/task_runner.py
apps/api/tests/test_plan_postgres.py
apps/api/tests/test_plans.py
apps/api/tests/test_postgres_integration.py
apps/api/tests/test_request_router.py
apps/api/tests/test_routing_integration.py
apps/api/tests/test_transfer_operations.py
apps/api/uv.lock
apps/web/features/conversation/ConversationPanel.tsx
apps/web/features/plans/PlanCard.tsx
apps/web/lib/api/client.ts
docs/archive/versions/implementation-report-v0.8.1.md
docs/archive/versions/repository-tree-v0.8.1.md
docs/archive/versions/test-results-v0.8.1.md
packages/api-client/src/schema.d.ts
scripts/smoke_plan_product.py
```

0016 只增加 Plan/DAG 必需表与索引；Task、Workflow、Operation、Event 的历史 schema 未重构。测试文件变化包含与新幂等语义一致的旧断言和 PostgreSQL fixture 隔离修正。
