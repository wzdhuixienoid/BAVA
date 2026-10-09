# 历史档案：Repository Tree v0.3.4

> 历史材料，保留原记录日期、版本和结论。旧风险规则、待办事项、测试数量与本地部署状态不代表 v0.10.3；当前说明见 [文档导航](../../README.md)。

Status: `IMPLEMENTED`

以下仅列出 v0.3.4 新增或主要修改的结构；v0.3.1–v0.3.3 的 Financial Analytics、Agent、Router 和 Skill 文件继续保留。

```text
banking-agent/
├── README.md
├── apps/
│   ├── api/
│   │   ├── migrations/versions/
│   │   │   └── 0005_reports.py
│   │   ├── src/banking_api/
│   │   │   ├── api/
│   │   │   │   ├── router.py
│   │   │   │   └── routes/
│   │   │   │       └── reports.py
│   │   │   ├── application/
│   │   │   │   ├── report_service.py
│   │   │   │   └── task_service.py
│   │   │   ├── domain/
│   │   │   │   ├── enums.py
│   │   │   │   ├── report.py
│   │   │   │   └── task.py
│   │   │   ├── persistence/
│   │   │   │   ├── models.py
│   │   │   │   └── repositories/
│   │   │   │       ├── conversations.py
│   │   │   │       ├── reports.py
│   │   │   │       └── tasks.py
│   │   │   ├── routing/
│   │   │   │   ├── models.py
│   │   │   │   └── request_router.py
│   │   │   ├── runtime/
│   │   │   │   └── task_runner.py
│   │   │   ├── skill_runtime/
│   │   │   │   └── executor.py
│   │   │   └── main.py
│   │   ├── tests/
│   │   │   ├── test_agent_task_e2e.py
│   │   │   ├── test_postgres_integration.py
│   │   │   ├── test_reports.py
│   │   │   ├── test_request_router.py
│   │   │   └── test_routing_integration.py
│   │   ├── pyproject.toml
│   │   └── uv.lock
│   └── web/
│       ├── app/
│       │   ├── page.tsx
│       │   └── reports/
│       │       ├── page.tsx
│       │       └── [reportId]/
│       │           └── page.tsx
│       ├── features/
│       │   ├── conversation/
│       │   │   └── ConversationPanel.tsx
│       │   ├── reports/
│       │   │   ├── CategoryBreakdown.tsx
│       │   │   ├── MonthlyReportView.tsx
│       │   │   ├── PeriodComparison.tsx
│       │   │   ├── ReportCard.tsx
│       │   │   ├── ReportInsights.tsx
│       │   │   ├── ReportList.tsx
│       │   │   ├── ReportOverview.tsx
│       │   │   ├── TopTransactions.tsx
│       │   │   └── presentation.ts
│       │   └── tasks/
│       │       ├── TaskItem.tsx
│       │       └── TaskPanel.tsx
│       └── lib/
│           ├── api/client.ts
│           └── events/sse.ts
├── packages/api-client/src/
│   └── schema.d.ts
├── scripts/
│   └── smoke_report_product.py
└── docs/
    ├── implementation-report-v0.3.4.md
    ├── repository-tree-v0.3.4.md
    └── test-results-v0.3.4.md
```

关键边界：

- `runtime/manual_agent_runtime.py` 未修改或扩展。
- 没有新增 Report Agent、Skill 或 Financial Tool。
- 没有 `POST/PATCH/PUT/DELETE /reports`。
- 没有 Chart、PDF/Excel、Report 编辑/删除、raw transaction search 或任何资金写操作。
- OpenAPI/Pydantic 仍是前端 Report TypeScript 类型的唯一 schema source。
