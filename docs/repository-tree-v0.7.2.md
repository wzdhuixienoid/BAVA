# Repository Tree v0.7.2

仅列出本版订阅管理与 v0.7.1 边界直接相关的文件。

```text
.
├── README.md
├── apps
│   ├── api
│   │   ├── migrations/versions/0014_subscription_cancellation.py
│   │   ├── src/banking_api
│   │   │   ├── agents/subscription_analysis_agent.py
│   │   │   ├── api/routes/subscriptions.py
│   │   │   ├── application
│   │   │   │   ├── operation_service.py
│   │   │   │   ├── transfer_risk_facts.py
│   │   │   │   └── workflow_service.py
│   │   │   ├── subscriptions
│   │   │   │   ├── detector.py
│   │   │   │   ├── models.py
│   │   │   │   ├── provider.py
│   │   │   │   └── service.py
│   │   │   ├── tools/subscriptions.py
│   │   │   └── workflows/subscription_cancel
│   │   │       ├── authorization.py
│   │   │       ├── engine.py
│   │   │       ├── intent_extractor.py
│   │   │       └── models.py
│   │   └── tests
│   │       ├── test_subscriptions.py
│   │       ├── test_transfer_risk.py
│   │       └── test_transfer_workflow.py
│   └── web
│       ├── app/subscriptions/page.tsx
│       └── features
│           ├── subscriptions/SubscriptionSummaryCard.tsx
│           └── workflows/subscriptions/SubscriptionCancellationCard.tsx
├── packages/api-client/src/schema.d.ts
└── docs
    ├── implementation-report-v0.7.2.md
    ├── repository-tree-v0.7.2.md
    └── test-results-v0.7.2.md
```
