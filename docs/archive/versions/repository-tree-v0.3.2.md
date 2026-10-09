# 历史档案：Repository Tree v0.3.2

> 历史材料，保留原记录日期、版本和结论。旧风险规则、待办事项、测试数量与本地部署状态不代表 v0.10.3；当前说明见 [文档导航](../../README.md)。

Status: `IMPLEMENTED`

```text
banking-agent/
├── README.md
├── apps/api/
│   ├── migrations/versions/
│   │   └── 0004_task_executor.py
│   ├── src/banking_api/
│   │   ├── agents/
│   │   │   ├── models.py
│   │   │   ├── minimal_banking_agent.py
│   │   │   └── financial_analysis_agent.py
│   │   ├── routing/
│   │   │   ├── __init__.py
│   │   │   ├── models.py
│   │   │   └── request_router.py
│   │   ├── registries/
│   │   │   └── agent_registry.py
│   │   ├── financial/
│   │   │   ├── analytics_service.py
│   │   │   └── analysis_snapshot.py
│   │   ├── runtime/
│   │   │   ├── base.py
│   │   │   ├── task_runner.py
│   │   │   └── langgraph/
│   │   │       ├── graph.py
│   │   │       └── state.py
│   │   ├── persistence/
│   │   │   ├── models.py
│   │   │   └── repositories/tasks.py
│   │   ├── application/
│   │   │   ├── conversation_service.py
│   │   │   └── task_service.py
│   │   ├── domain/{enums.py,task.py}
│   │   ├── context/builder.py
│   │   ├── tools/banking/
│   │   │   ├── list_accounts.py
│   │   │   └── four financial tool builders
│   │   └── main.py
│   └── tests/
│       ├── test_request_router.py
│       ├── test_financial_analysis_agent.py
│       ├── test_financial_agent_grounding.py
│       └── test_routing_integration.py
├── packages/api-client/src/schema.d.ts
├── scripts/
│   ├── generate_golden_financial_metrics.py
│   └── smoke_routing.py
└── docs/
    ├── golden-financial-data-v0.3.2.md
    ├── implementation-report-v0.3.2.md
    ├── repository-tree-v0.3.2.md
    └── test-results-v0.3.2.md
```

`runtime/manual_agent_runtime.py` 未修改。本轮未新增 Skill、Report、Chart、Reports API、raw transaction search、Memory、RAG、MCP、Planner、Agent-to-Agent 调用或写操作。
