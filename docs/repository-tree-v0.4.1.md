# Repository Tree v0.4.1

Relevant 04.1 additions and modifications:

```text
apps/api/
├── migrations/versions/
│   └── 0006_transfer_workflows.py
├── src/banking_api/
│   ├── api/routes/workflows.py
│   ├── application/workflow_service.py
│   ├── domain/
│   │   ├── enums.py
│   │   └── workflow.py
│   ├── persistence/
│   │   ├── models.py
│   │   └── repositories/workflows.py
│   ├── routing/
│   │   ├── models.py
│   │   └── request_router.py
│   ├── runtime/task_runner.py
│   ├── tools/
│   │   ├── models.py
│   │   └── banking/search_payees.py
│   └── workflows/transfer/
│       ├── __init__.py
│       ├── engine.py
│       ├── intent_extractor.py
│       ├── models.py
│       └── validation.py
└── tests/
    ├── test_transfer_workflow.py
    └── test_postgres_integration.py

apps/web/
├── features/workflows/transfer/
│   └── TransferWorkflowCard.tsx
├── features/conversation/ConversationPanel.tsx
├── features/tasks/
│   ├── TaskItem.tsx
│   └── TaskPanel.tsx
├── lib/api/client.ts
└── lib/events/sse.ts

packages/api-client/src/schema.d.ts
scripts/smoke_transfer_draft.py
docs/
├── implementation-report-v0.4.1.md
├── repository-tree-v0.4.1.md
└── test-results-v0.4.1.md
```

No `TransferAgent`, `PaymentAgent`, approval table, operation table, or transfer write tool was added.
