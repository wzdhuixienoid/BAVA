# 历史档案：Repository Tree v0.5.3

> 历史材料，保留原记录日期、版本和结论。旧风险规则、待办事项、测试数量与本地部署状态不代表 v0.10.3；当前说明见 [文档导航](../../README.md)。

Only files central to v0.5.3 are shown.

```text
banking-agent/
├── README.md
├── .env.example
├── docker-compose.yml
├── apps/api/
│   ├── migrations/versions/
│   │   └── 0011_transactional_outbox.py
│   ├── src/banking_api/
│   │   ├── application/
│   │   │   └── outbox_publication_policy.py
│   │   ├── config/settings.py
│   │   ├── persistence/
│   │   │   ├── models.py
│   │   │   └── repositories/outbox.py
│   │   ├── runtime/
│   │   │   ├── event_publisher.py
│   │   │   └── outbox_publisher.py
│   │   └── main.py
│   └── tests/
│       ├── test_outbox.py
│       ├── test_events.py
│       └── test_postgres_integration.py
└── docs/
    ├── implementation-report-v0.5.3.md
    ├── repository-tree-v0.5.3.md
    └── test-results-v0.5.3.md
```

Existing Conversation, Task, Report, Workflow, Approval, Reauthentication, and Operation producers
now use the centralized Event + Outbox persistence primitive. Their public domain contracts were
not changed. No frontend product surface or public Outbox API was added.
