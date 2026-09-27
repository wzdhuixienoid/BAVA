# Repository Tree v0.5.2

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
