# 历史档案：Repository Tree v0.6.1

> 历史材料，保留原记录日期、版本和结论。旧风险规则、待办事项、测试数量与本地部署状态不代表 v0.10.3；当前说明见 [文档导航](../../README.md)。

Only files central to the v0.6.1 authentication and Principal boundary are shown. Existing v0.5.x reliability internals remain in place.

```text
.
├── .env.example
├── README.md
├── docker-compose.yml
├── apps
│   ├── api
│   │   ├── migrations/versions
│   │   │   └── 0013_oidc_identity_and_task_owner.py
│   │   ├── pyproject.toml
│   │   ├── src/banking_api
│   │   │   ├── api
│   │   │   │   ├── dependencies.py
│   │   │   │   └── routes
│   │   │   │       ├── conversations.py
│   │   │   │       ├── events.py
│   │   │   │       ├── operations.py
│   │   │   │       ├── reports.py
│   │   │   │       ├── tasks.py
│   │   │   │       └── workflows.py
│   │   │   ├── application
│   │   │   │   ├── conversation_service.py
│   │   │   │   ├── operation_service.py
│   │   │   │   └── workflow_service.py
│   │   │   ├── config/settings.py
│   │   │   ├── domain/principal.py
│   │   │   ├── financial/analytics_service.py
│   │   │   ├── mock_bank/service.py
│   │   │   ├── persistence
│   │   │   │   ├── models.py
│   │   │   │   └── repositories
│   │   │   │       ├── identities.py
│   │   │   │       └── tasks.py
│   │   │   ├── runtime
│   │   │   │   ├── base.py
│   │   │   │   └── task_runner.py
│   │   │   ├── security/authentication
│   │   │   │   ├── __init__.py
│   │   │   │   ├── jwks.py
│   │   │   │   ├── provision.py
│   │   │   │   └── service.py
│   │   │   ├── tools
│   │   │   │   ├── banking/*.py
│   │   │   │   ├── executor.py
│   │   │   │   └── models.py
│   │   │   ├── transfers
│   │   │   │   ├── mock_provider.py
│   │   │   │   └── provider.py
│   │   │   └── workflows/transfer/engine.py
│   │   └── tests
│   │       ├── test_authentication.py
│   │       ├── test_principal_isolation.py
│   │       ├── test_postgres_integration.py
│   │       ├── test_transfer_authorization.py
│   │       ├── test_transfer_operations.py
│   │       └── test_transfer_workflow.py
│   └── web
│       ├── app/auth/popup-callback/page.tsx
│       ├── components/auth/AuthGate.tsx
│       ├── lib
│       │   ├── api/client.ts
│       │   ├── auth/AuthProvider.tsx
│       │   └── events/sse.ts
│       └── package.json
└── docs
    ├── implementation-report-v0.6.1.md
    ├── repository-tree-v0.6.1.md
    └── test-results-v0.6.1.md
```
