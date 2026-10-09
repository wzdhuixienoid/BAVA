# 历史档案：Repository Tree v0.5.1

> 历史材料，保留原记录日期、版本和结论。旧风险规则、待办事项、测试数量与本地部署状态不代表 v0.10.3；当前说明见 [文档导航](../../README.md)。

Only files central to v0.5.1 are shown.

```text
banking-agent/
├── README.md
├── .env.example
├── docker-compose.yml
├── apps/
│   ├── api/
│   │   ├── migrations/versions/
│   │   │   └── 0009_operation_recovery.py
│   │   ├── src/banking_api/
│   │   │   ├── application/
│   │   │   │   ├── operation_recovery_policy.py  # bounded backoff + lease policy
│   │   │   │   └── operation_service.py          # shared manual/background reconciliation
│   │   │   ├── config/settings.py                  # recovery configuration
│   │   │   ├── domain/operation.py                 # internal + safe recovery metadata
│   │   │   ├── persistence/
│   │   │   │   ├── models.py                          # schedule/attempt/lease columns + index
│   │   │   │   └── repositories/operations.py         # SKIP LOCKED claim + fenced update
│   │   │   ├── runtime/operation_recovery_worker.py # explicit polling lifecycle
│   │   │   └── main.py                             # FastAPI start/stop integration
│   │   └── tests/
│   │       ├── test_operation_recovery.py       # unit/in-process recovery behavior
│   │       └── test_postgres_integration.py     # independent-session claim/crash/exact-once
│   └── web/                                      # no product UI added
├── packages/api-client/src/schema.d.ts               # regenerated OpenAPI types
└── docs/
    ├── implementation-report-v0.5.1.md
    ├── repository-tree-v0.5.1.md
    └── test-results-v0.5.1.md
```

The v0.4.3 documents and migration remain unchanged as architecture/audit history.
