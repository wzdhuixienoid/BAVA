# 历史档案：Repository Tree v0.3.1

> 历史材料，保留原记录日期、版本和结论。旧风险规则、待办事项、测试数量与本地部署状态不代表 v0.10.3；当前说明见 [文档导航](../../README.md)。

Status: `IMPLEMENTED`

下列结构聚焦 v0.3.1 新增或直接修改的文件。Runtime、persistence、API routes 和 frontend source 结构保持 v0.2.2 现状。

```text
banking-agent/
├── README.md
├── apps/
│   └── api/
│       ├── pyproject.toml
│       ├── uv.lock
│       ├── src/banking_api/
│       │   ├── main.py
│       │   ├── financial/
│       │   │   ├── __init__.py
│       │   │   ├── models.py
│       │   │   ├── errors.py
│       │   │   └── analytics_service.py
│       │   ├── mock_bank/
│       │   │   ├── service.py
│       │   │   └── data/
│       │   │       └── golden_financial_metrics.json
│       │   └── tools/
│       │       ├── models.py
│       │       ├── executor.py
│       │       └── banking/
│       │           ├── __init__.py
│       │           ├── get_spending_summary.py
│       │           ├── get_category_breakdown.py
│       │           ├── compare_spending_periods.py
│       │           └── get_top_transactions.py
│       └── tests/
│           ├── test_financial_analytics.py
│           ├── test_financial_tools.py
│           └── test_financial_golden.py
├── scripts/
│   └── generate_golden_financial_metrics.py
└── docs/
    ├── golden-financial-data-v0.3.1.md
    ├── implementation-report-v0.3.1.md
    ├── repository-tree-v0.3.1.md
    └── test-results-v0.3.1.md
```

明确未新增：

- FinancialAnalysisAgent / Agent registry entry
- Skill / Report / Chart / UI / product API
- Transaction database migration
- `transaction.search`
- Memory / RAG / MCP / Multi-Agent / Planner / Workflow
- 任何新写操作
