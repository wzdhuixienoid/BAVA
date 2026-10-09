# 历史档案：AI Banking Agent — Repository Tree v0.2.2

> 历史材料，保留原记录日期、版本和结论。旧风险规则、待办事项、测试数量与本地部署状态不代表 v0.10.3；当前说明见 [文档导航](../../README.md)。

范围：02.2 源码与交付文档。省略 `.git`、`.env`、virtualenv、`node_modules`、`.next`、cache 和 PostgreSQL volume。

```text
banking-agent/
├── .env.example
├── README.md
├── Makefile
├── docker-compose.yml
├── apps/
│   ├── api/
│   │   ├── Dockerfile
│   │   ├── pyproject.toml
│   │   ├── uv.lock
│   │   ├── migrations/versions/
│   │   │   ├── 0001_bootstrap.py
│   │   │   ├── 0002_agent_task_progress.py
│   │   │   └── 0003_task_runtime_backend.py
│   │   ├── src/banking_api/
│   │   │   ├── agents/minimal_banking_agent.py
│   │   │   ├── api/routes/{conversations,events,health,tasks}.py
│   │   │   ├── application/{conversation_service,task_service}.py
│   │   │   ├── config/settings.py
│   │   │   ├── context/builder.py
│   │   │   ├── domain/{conversation,enums,event,message,task}.py
│   │   │   ├── llm/
│   │   │   │   ├── models.py
│   │   │   │   ├── provider.py
│   │   │   │   ├── fake_provider.py
│   │   │   │   └── openai_compatible_provider.py
│   │   │   ├── mock_bank/
│   │   │   │   ├── service.py
│   │   │   │   └── data/{accounts,transactions,payees,subscriptions}.json
│   │   │   ├── persistence/
│   │   │   │   ├── database.py
│   │   │   │   ├── models.py
│   │   │   │   └── repositories/{conversations,events,messages,tasks}.py
│   │   │   ├── policy/service.py
│   │   │   ├── registries/tool_registry.py
│   │   │   ├── runtime/
│   │   │   │   ├── base.py
│   │   │   │   ├── agent_runtime.py
│   │   │   │   ├── manual_agent_runtime.py
│   │   │   │   ├── runtime_factory.py
│   │   │   │   ├── task_runner.py
│   │   │   │   ├── task_reconciliation.py
│   │   │   │   ├── event_bus.py
│   │   │   │   ├── event_publisher.py
│   │   │   │   └── langgraph/
│   │   │   │       ├── __init__.py
│   │   │   │       ├── state.py
│   │   │   │       ├── graph.py
│   │   │   │       └── checkpoint.py
│   │   │   └── tools/
│   │   │       ├── models.py
│   │   │       ├── executor.py
│   │   │       └── banking/{list_accounts,get_balance}.py
│   │   └── tests/
│   │       ├── test_agent_runtime.py
│   │       ├── test_runtime_parity.py
│   │       ├── test_runtime_hardening.py
│   │       ├── test_postgres_integration.py
│   │       └── test_*.py
│   └── web/
│       ├── app/{layout,page}.tsx
│       ├── components/agent-ui/TaskStatus.tsx
│       └── features/tasks/{TaskItem,TaskPanel,TaskProgress}.tsx
├── packages/api-client/src/schema.d.ts
├── scripts/{generate_mock_data,validate_mock_data,smoke_agent}.py
└── docs/
    ├── implementation-report-v0.2.2.md
    ├── repository-tree-v0.2.2.md
    ├── test-results-v0.2.2.md
    ├── runtime-comparison-v0.2.2.md
    └── historical v0.1/v0.2 documents
```

## 02.2 新增边界

- `runtime/base.py`：Provider-neutral Runtime request/result/state/error Protocol。
- `manual_agent_runtime.py`：保留的 Reference Implementation。
- `runtime/langgraph/`：直接 `StateGraph`、可序列化 state 和 PostgreSQL checkpoint lifecycle。
- `runtime_factory.py`：按 Task 已冻结 backend 选择 Runtime。
- `task_reconciliation.py`：启动时将遗留 `PENDING/RUNNING` 转为 `INTERRUPTED`。
- `0003_task_runtime_backend.py`：`runtime_backend` 与 `INTERRUPTED` Domain schema。

LangGraph 自己的 `checkpoints`、`checkpoint_blobs`、`checkpoint_writes`、`checkpoint_migrations` 表由 saver `setup()` 创建，故意不出现在 SQLAlchemy Domain model 或 Alembic migration 中。
