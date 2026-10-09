# 历史档案：Repository Tree v0.7.1

> 历史材料，保留原记录日期、版本和结论。旧风险规则、待办事项、测试数量与本地部署状态不代表 v0.10.3；当前说明见 [文档导航](../../README.md)。

仅列出与动态风险分级直接相关的文件。

```text
.
├── .env.example
├── README.md
├── apps
│   ├── api
│   │   ├── pyproject.toml
│   │   ├── src/banking_api
│   │   │   ├── application
│   │   │   │   ├── operation_service.py
│   │   │   │   ├── transfer_risk_facts.py
│   │   │   │   └── workflow_service.py
│   │   │   ├── config/settings.py
│   │   │   ├── domain
│   │   │   │   ├── risk.py
│   │   │   │   └── workflow.py
│   │   │   ├── policy/service.py
│   │   │   └── workflows/transfer
│   │   │       ├── models.py
│   │   │       └── risk.py
│   │   └── tests
│   │       ├── test_postgres_integration.py
│   │       ├── test_transfer_authorization.py
│   │       ├── test_transfer_operations.py
│   │       └── test_transfer_risk.py
│   └── web/features/workflows/transfer/TransferWorkflowCard.tsx
├── packages/api-client/src/schema.d.ts
└── docs
    ├── implementation-report-v0.7.1.md
    ├── repository-tree-v0.7.1.md
    └── test-results-v0.7.1.md
```

没有新增数据表或 Alembic migration。当前 RiskDecision 使用现有 Workflow typed `state_json` 持久化，历史使用现有 Event + Outbox。
