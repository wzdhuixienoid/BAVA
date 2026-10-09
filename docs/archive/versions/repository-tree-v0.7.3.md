# 历史档案：Repository Tree v0.7.3

> 历史材料，保留原记录日期、版本和结论。旧风险规则、待办事项、测试数量与本地部署状态不代表 v0.10.3；当前说明见 [文档导航](../../README.md)。

仅列出本版异常分析与 Security Guard 直接相关文件。

```text
.
├── .env.example
├── README.md
├── apps
│  ├── api
│  │  ├── migrations/versions/0015_security_guard.py
│  │  ├── src/banking_api
│  │  │  ├── agents/financial_analysis_agent.py
│  │  │  ├── api/routes/security.py
│  │  │  ├── application
│  │  │  │  ├── operation_service.py
│  │  │  │  └── workflow_service.py
│  │  │  ├── financial
│  │  │  │  ├── anomaly_detector.py
│  │  │  │  └── anomaly_models.py
│  │  │  ├── persistence/models.py
│  │  │  ├── security/guard.py
│  │  │  └── tools/banking/detect_anomalies.py
│  │  └── tests
│  │     ├── test_financial_analysis_agent.py
│  │     ├── test_postgres_integration.py
│  │     ├── test_security_guard.py
│  │     ├── test_transaction_anomalies.py
│  │     └── test_transfer_authorization.py
│  └── web
│     └── features
│        ├── anomalies/TransactionAnomalyCard.tsx
│        └── security/SecurityStatusBanner.tsx
├── packages/api-client/src/schema.d.ts
├── scripts/smoke_routing.py
└── docs
   ├── implementation-report-v0.7.3.md
   ├── repository-tree-v0.7.3.md
   └── test-results-v0.7.3.md
```
