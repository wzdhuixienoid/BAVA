# 历史档案：AI Banking Agent — Repository Tree v0.2

> 历史材料，保留原记录日期、版本和结论。旧风险规则、待办事项、测试数量与本地部署状态不代表 v0.10.3；当前说明见 [文档导航](../../README.md)。

生成日期：`2026-09-20`

范围：02.1 Minimal Agent Runtime v0.2 项目源文件。排除 `.git`、`.env`、虚拟环境、`node_modules`、`.next`、cache、数据库 volume 和本地 `.DS_Store`。

```text
banking-agent/
├── apps/
│   ├── api/
│   │   ├── .dockerignore
│   │   ├── Dockerfile
│   │   ├── alembic.ini
│   │   ├── pyproject.toml
│   │   ├── uv.lock
│   │   ├── migrations/
│   │   │   ├── env.py
│   │   │   ├── script.py.mako
│   │   │   └── versions/
│   │   │       ├── 0001_bootstrap.py
│   │   │       └── 0002_agent_task_progress.py
│   │   ├── src/
│   │   │   └── banking_api/
│   │   │       ├── __init__.py
│   │   │       ├── main.py
│   │   │       ├── agents/
│   │   │       │   ├── README.md
│   │   │       │   ├── __init__.py
│   │   │       │   └── minimal_banking_agent.py
│   │   │       ├── api/
│   │   │       │   ├── __init__.py
│   │   │       │   ├── dependencies.py
│   │   │       │   ├── router.py
│   │   │       │   └── routes/
│   │   │       │       ├── __init__.py
│   │   │       │       ├── conversations.py
│   │   │       │       ├── events.py
│   │   │       │       ├── health.py
│   │   │       │       └── tasks.py
│   │   │       ├── application/
│   │   │       │   ├── __init__.py
│   │   │       │   ├── conversation_service.py
│   │   │       │   └── task_service.py
│   │   │       ├── audit/
│   │   │       │   └── README.md
│   │   │       ├── config/
│   │   │       │   ├── __init__.py
│   │   │       │   └── settings.py
│   │   │       ├── context/
│   │   │       │   ├── __init__.py
│   │   │       │   └── builder.py
│   │   │       ├── domain/
│   │   │       │   ├── __init__.py
│   │   │       │   ├── approval.py
│   │   │       │   ├── conversation.py
│   │   │       │   ├── enums.py
│   │   │       │   ├── event.py
│   │   │       │   ├── message.py
│   │   │       │   ├── operation.py
│   │   │       │   ├── task.py
│   │   │       │   └── workflow.py
│   │   │       ├── knowledge/
│   │   │       │   └── README.md
│   │   │       ├── llm/
│   │   │       │   ├── __init__.py
│   │   │       │   ├── fake_provider.py
│   │   │       │   ├── models.py
│   │   │       │   ├── openai_compatible_provider.py
│   │   │       │   └── provider.py
│   │   │       ├── memory/
│   │   │       │   └── README.md
│   │   │       ├── mock_bank/
│   │   │       │   ├── __init__.py
│   │   │       │   ├── service.py
│   │   │       │   └── data/
│   │   │       │       ├── accounts.json
│   │   │       │       ├── payees.json
│   │   │       │       ├── subscriptions.json
│   │   │       │       └── transactions.json
│   │   │       ├── persistence/
│   │   │       │   ├── __init__.py
│   │   │       │   ├── database.py
│   │   │       │   ├── models.py
│   │   │       │   └── repositories/
│   │   │       │       ├── __init__.py
│   │   │       │       ├── conversations.py
│   │   │       │       ├── events.py
│   │   │       │       ├── messages.py
│   │   │       │       └── tasks.py
│   │   │       ├── policy/
│   │   │       │   ├── __init__.py
│   │   │       │   └── service.py
│   │   │       ├── registries/
│   │   │       │   ├── __init__.py
│   │   │       │   ├── agent_registry.py
│   │   │       │   ├── skill_registry.py
│   │   │       │   ├── tool_registry.py
│   │   │       │   └── workflow_registry.py
│   │   │       ├── runtime/
│   │   │       │   ├── __init__.py
│   │   │       │   ├── agent_runtime.py
│   │   │       │   ├── event_bus.py
│   │   │       │   ├── event_publisher.py
│   │   │       │   └── task_runner.py
│   │   │       ├── skills/
│   │   │       │   └── README.md
│   │   │       ├── tools/
│   │   │       │   ├── __init__.py
│   │   │       │   ├── executor.py
│   │   │       │   ├── models.py
│   │   │       │   └── banking/
│   │   │       │       ├── __init__.py
│   │   │       │       ├── get_balance.py
│   │   │       │       └── list_accounts.py
│   │   │       └── workflows/
│   │   │           └── README.md
│   │   └── tests/
│   │       ├── conftest.py
│   │       ├── test_agent_runtime.py
│   │       ├── test_agent_task_e2e.py
│   │       ├── test_conversations.py
│   │       ├── test_events.py
│   │       ├── test_health.py
│   │       ├── test_llm_provider.py
│   │       ├── test_mock_data.py
│   │       ├── test_postgres_integration.py
│   │       ├── test_tasks.py
│   │       └── test_tool_executor.py
│   └── web/
│       ├── Dockerfile
│       ├── eslint.config.mjs
│       ├── next-env.d.ts
│       ├── next.config.ts
│       ├── package.json
│       ├── postcss.config.mjs
│       ├── tailwind.config.ts
│       ├── tsconfig.json
│       ├── app/
│       │   ├── globals.css
│       │   ├── layout.tsx
│       │   └── page.tsx
│       ├── components/
│       │   └── agent-ui/
│       │       └── TaskStatus.tsx
│       ├── features/
│       │   ├── conversation/
│       │   │   ├── ConversationPanel.tsx
│       │   │   ├── MessageComposer.tsx
│       │   │   └── MessageList.tsx
│       │   └── tasks/
│       │       ├── TaskItem.tsx
│       │       ├── TaskPanel.tsx
│       │       └── TaskProgress.tsx
│       ├── lib/
│       │   ├── api/
│       │   │   └── client.ts
│       │   └── events/
│       │       └── sse.ts
│       └── public/
│           └── .gitkeep
├── docs/
│   ├── architecture-baseline-v0.1.md
│   ├── codex-bootstrap-v0.1.md
│   ├── implementation-report-v0.1.md
│   ├── implementation-report-v0.2.md
│   ├── repository-tree-v0.1.md
│   ├── repository-tree-v0.2.md
│   ├── test-results-v0.1.md
│   ├── test-results-v0.2.md
│   └── testing-guide-v0.2.md
├── infra/
│   └── postgres/
│       └── README.md
├── packages/
│   └── api-client/
│       ├── package.json
│       └── src/
│           ├── index.ts
│           └── schema.d.ts
├── scripts/
│   ├── generate_mock_data.py
│   ├── smoke_agent.py
│   └── validate_mock_data.py
├── .dockerignore
├── .env.example
├── .gitignore
├── Makefile
├── README.md
├── docker-compose.yml
├── package.json
├── pnpm-lock.yaml
└── pnpm-workspace.yaml
```

## 关键边界

- `llm/` 是唯一 Provider adapter 边界；Runtime 不依赖 provider-native response。
- `runtime/agent_runtime.py` 是手写 Agent Loop；`runtime/task_runner.py` 负责持久化生命周期。
- `tools/` 只含两个只读正式能力；未来数据文件不等于当前 Tool 权限。
- `mock_bank/data/` 是 committed、deterministic、完全虚构的数据集。
- `policy/service.py` 实现唯一 ALLOW 规则和 Default Deny。
- `events` 表是事件持久事实；`event_bus.py` 只负责单进程实时 fan-out。
- v0.1 文档作为历史快照保留；v0.2 三份交付文档描述当前实现。
