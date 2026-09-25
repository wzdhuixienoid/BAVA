# Repository Tree v0.4.2

Only files central to 04.2 are shown.

```text
banking-agent/
├── .env.example                                      # Approval/Reauth TTL and local provider config
├── README.md                                         # READY_FOR_COMMIT safety semantics and API map
├── docker-compose.yml                                # Server-side authorization configuration
├── apps/
│   ├── api/
│   │   ├── migrations/versions/
│   │   │   └── 0007_transfer_approval_reauth.py      # approvals + reauthentications; no operations table
│   │   ├── src/banking_api/
│   │   │   ├── api/routes/workflows.py               # deterministic Workflow Action endpoints
│   │   │   ├── application/workflow_service.py       # state transitions, TTL, invalidation, concurrency
│   │   │   ├── config/settings.py                    # TTL, attempts, local provider secret
│   │   │   ├── domain/
│   │   │   │   ├── approval.py                       # Approval resource and safe summary
│   │   │   │   ├── reauthentication.py               # Reauthentication resource and safe summary
│   │   │   │   ├── enums.py                          # authorization/workflow statuses
│   │   │   │   └── workflow.py                       # safe summaries on Workflow resource
│   │   │   ├── persistence/
│   │   │   │   ├── models.py                         # SQLAlchemy approval/reauth models
│   │   │   │   └── repositories/
│   │   │   │       ├── approvals.py
│   │   │   │       └── reauthentications.py
│   │   │   ├── security/reauthentication/
│   │   │   │   ├── provider.py                       # replaceable protocol
│   │   │   │   └── mock_provider.py                  # local/test implementation
│   │   │   └── workflows/transfer/
│   │   │       ├── authorization.py                  # canonical JSON + SHA-256
│   │   │       ├── engine.py                         # deterministic revalidation/options
│   │   │       └── models.py                         # auth snapshot and action contracts
│   │   └── tests/
│   │       ├── test_transfer_authorization.py        # fake E2E, TTL, attempts, mutation/security
│   │       └── test_postgres_integration.py          # migration, persistence, recovery, ownership
│   └── web/
│       ├── features/workflows/transfer/
│       │   └── TransferWorkflowCard.tsx              # review, approval, reauth, ready/edit UI
│       └── lib/
│           ├── api/client.ts                         # action clients
│           └── events/sse.ts                         # workflow/approval/reauth refresh signals
├── packages/api-client/src/schema.d.ts               # generated OpenAPI TypeScript contract
├── scripts/
│   └── smoke_transfer_authorization.py               # real DeepSeek + deterministic auth smoke
└── docs/
    ├── implementation-report-v0.4.2.md
    ├── repository-tree-v0.4.2.md
    └── test-results-v0.4.2.md
```
