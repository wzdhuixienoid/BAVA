# AI Banking Agent — Repository Tree v0.1

生成日期：`2026-09-20`  
范围：项目源文件；排除 `.git`、虚拟环境、`node_modules`、`.next`、cache 和本地 `.DS_Store`。

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
│   │   │       └── 0001_bootstrap.py
│   │   ├── src/
│   │   │   └── banking_api/
│   │   │       ├── __init__.py
│   │   │       ├── main.py
│   │   │       ├── agents/
│   │   │       │   └── README.md
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
│   │   │       │   ├── bootstrap_runtime.py
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
│   │   │       ├── memory/
│   │   │       │   └── README.md
│   │   │       ├── mock_bank/
│   │   │       │   ├── __init__.py
│   │   │       │   └── service.py
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
│   │   │       │   ├── event_bus.py
│   │   │       │   └── event_publisher.py
│   │   │       ├── skills/
│   │   │       │   └── README.md
│   │   │       └── workflows/
│   │   │           └── README.md
│   │   └── tests/
│   │       ├── conftest.py
│   │       ├── test_conversations.py
│   │       ├── test_events.py
│   │       ├── test_health.py
│   │       └── test_tasks.py
│   └── web/
│       ├── Dockerfile
│       ├── package.json
│       ├── eslint.config.mjs
│       ├── next-env.d.ts
│       ├── next.config.ts
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
│       │       └── TaskPanel.tsx
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
│   ├── repository-tree-v0.1.md
│   └── test-results-v0.1.md
├── infra/
│   └── postgres/
│       └── README.md
├── packages/
│   └── api-client/
│       ├── package.json
│       └── src/
│           ├── index.ts
│           └── schema.d.ts
├── .dockerignore
├── .env.example
├── .gitignore
├── AI Banking Agent v0.1
├── Makefile
├── README.md
├── docker-compose.yml
├── package.json
├── pnpm-lock.yaml
└── pnpm-workspace.yaml
```

