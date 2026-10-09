# 历史档案：Repository Tree v0.5.2

> 历史材料，保留原记录日期、版本和结论。旧风险规则、待办事项、测试数量与本地部署状态不代表 v0.10.3；当前说明见 [文档导航](../../README.md)。

Only files central to v0.5.2 are shown.

```text
banking-agent/
├── README.md
├── apps/api/
│   ├── migrations/versions/
│   │   └── 0010_provider_transfer_errors.py
│   ├── src/banking_api/
│   │   ├── main.py                              # API version 0.5.2
│   │   ├── persistence/models.py                # durable provider error facts
│   │   └── transfers/mock_provider.py            # advisory lock + atomic funds decision
│   └── tests/
│       ├── test_provider_concurrency.py             # cross-process provider invariants
│       └── test_postgres_integration.py             # Operation/recovery interaction
└── docs/
    ├── implementation-report-v0.5.2.md
    ├── repository-tree-v0.5.2.md
    └── test-results-v0.5.2.md
```

No new frontend product surface, Agent, generic worker, lock framework, or reservation model was
added. All earlier version documents remain in `docs/` as architecture/audit history.
