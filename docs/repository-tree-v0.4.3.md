# Repository Tree v0.4.3

Only files central to 04.3 are shown.

```text
banking-agent/
├── README.md
├── apps/
│   ├── api/
│   │   ├── migrations/versions/
│   │   │   └── 0008_transfer_operations.py
│   │   ├── src/banking_api/
│   │   │   ├── api/routes/
│   │   │   │   ├── workflows.py          # commit action
│   │   │   │   └── operations.py         # owned GET + reconcile
│   │   │   ├── application/
│   │   │   │   ├── operation_service.py  # atomic prepare + reconciliation
│   │   │   │   └── workflow_service.py   # safe operation summary/cancel boundary
│   │   │   ├── domain/
│   │   │   │   ├── operation.py          # internal and frontend-safe models
│   │   │   │   ├── approval.py           # consumed operation linkage
│   │   │   │   ├── workflow.py           # operation summary
│   │   │   │   └── enums.py              # Operation/R4/Workflow statuses
│   │   │   ├── persistence/
│   │   │   │   ├── models.py             # operations + mock_bank_transfers
│   │   │   │   └── repositories/operations.py
│   │   │   ├── tools/banking/
│   │   │   │   ├── commit_transfer.py    # R4, operation_id-only input
│   │   │   │   ├── get_transfer_status.py
│   │   │   │   └── get_balance.py        # effective provider-ledger balance
│   │   │   ├── transfers/
│   │   │   │   ├── provider.py           # replaceable protocol/result semantics
│   │   │   │   └── mock_provider.py      # persistent idempotency ledger
│   │   │   └── workflows/transfer/
│   │   │       ├── engine.py             # Tool/Policy execution boundary
│   │   │       └── models.py             # commit action contract
│   │   └── tests/
│   │       ├── test_transfer_operations.py    # exact-once/fault/crash/security E2E
│   │       └── test_postgres_integration.py   # migration/persistence/recovery
│   └── web/
│       ├── features/workflows/transfer/TransferWorkflowCard.tsx
│       └── lib/
│           ├── api/client.ts                       # commit/operation/reconcile clients
│           └── events/sse.ts                       # operation.* refresh signals
├── packages/api-client/src/schema.d.ts                 # generated OpenAPI contract
├── scripts/smoke_transfer_operation.py                # real DeepSeek operation smoke
└── docs/
    ├── implementation-report-v0.4.3.md
    ├── repository-tree-v0.4.3.md
    └── test-results-v0.4.3.md
```
