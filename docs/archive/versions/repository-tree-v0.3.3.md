# 历史档案：Repository Tree v0.3.3

> 历史材料，保留原记录日期、版本和结论。旧风险规则、待办事项、测试数量与本地部署状态不代表 v0.10.3；当前说明见 [文档导航](../../README.md)。

Status: `IMPLEMENTED`

```text
banking-agent/
├── README.md
├── apps/api/
│   ├── src/banking_api/
│   │   ├── financial/
│   │   │   ├── analysis_snapshot.py
│   │   │   ├── report_models.py
│   │   │   └── report_formatter.py
│   │   ├── skills/
│   │   │   ├── __init__.py
│   │   │   ├── README.md
│   │   │   ├── models.py
│   │   │   └── monthly_spending_report.py
│   │   ├── skill_runtime/
│   │   │   ├── __init__.py
│   │   │   └── executor.py
│   │   ├── registries/
│   │   │   └── skill_registry.py
│   │   ├── mock_bank/data/
│   │   │   └── golden_monthly_report_core.json
│   │   └── main.py
│   └── tests/
│       ├── test_monthly_spending_report_skill.py
│       └── test_monthly_report_grounding.py
├── scripts/
│   ├── generate_golden_monthly_report_core.py
│   └── smoke_monthly_report_skill.py
└── docs/
    ├── golden-monthly-report-v0.3.3.md
    ├── implementation-report-v0.3.3.md
    ├── repository-tree-v0.3.3.md
    └── test-results-v0.3.3.md
```

`runtime/manual_agent_runtime.py` 未修改。本轮未新增 Agent、Financial Tool、Router route、Reports 持久化/API/UI、Chart、PDF、raw transaction search 或写操作。
