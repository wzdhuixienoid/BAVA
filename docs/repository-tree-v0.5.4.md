# Repository Tree v0.5.4

Only files central to v0.5.4 are shown. Existing v0.5.1 Operation recovery, v0.5.2 Provider
serialization, and v0.5.3 Outbox files remain unchanged reliability boundaries.

```text
banking-agent/
├── README.md
├── .env.example
├── docker-compose.yml
├── apps/api/
│   ├── pyproject.toml
│   ├── uv.lock
│   ├── migrations/versions/
│   │   └── 0012_durable_task_execution.py
│   ├── src/banking_api/
│   │   ├── api/routes/conversations.py
│   │   ├── application/
│   │   │   ├── task_execution_policy.py
│   │   │   └── workflow_service.py
│   │   ├── config/settings.py
│   │   ├── persistence/
│   │   │   ├── models.py
│   │   │   └── repositories/
│   │   │       ├── tasks.py
│   │   │       └── workflows.py
│   │   ├── runtime/
│   │   │   ├── task_execution_worker.py
│   │   │   ├── task_runner.py
│   │   │   └── task_reconciliation.py
│   │   └── main.py
│   └── tests/
│       ├── test_task_execution.py
│       ├── test_postgres_integration.py
│       ├── test_transfer_workflow.py
│       ├── test_runtime_hardening.py
│       ├── test_conversations.py
│       ├── test_tasks.py
│       ├── test_events.py
│       └── test_routing_integration.py
└── docs/
    ├── implementation-report-v0.5.4.md
    ├── repository-tree-v0.5.4.md
    └── test-results-v0.5.4.md
```

No public worker/job/lease endpoint and no worker dashboard were added. The Task execution fields
stay in persistence; existing Task resource responses remain the product surface.

