# 历史档案：AI Banking Agent — Implementation Report v0.1

> 历史材料，保留原记录日期、版本和结论。旧风险规则、待办事项、测试数量与本地部署状态不代表 v0.10.3；当前说明见 [文档导航](../../README.md)。

Status: `BOOTSTRAP IMPLEMENTED AND VALIDATED`  
Architecture baseline: `v0.1`  
Bootstrap iteration: `Iteration 0`  
Report date: `2026-09-20`

## 1. Created files

项目已建立完整 Monorepo 骨架，主要交付包括：

- Root：Compose、pnpm workspace、Makefile、环境变量模板、ignore 配置和项目 README。
- Backend：FastAPI application、Domain Schema、SQLAlchemy persistence、Alembic migration、Application Services、Bootstrap Runtime、SSE transport、Repositories、Registry/Policy/Context/MockBank 边界及测试。
- Frontend：Next.js App Router、Conversation/Message/Task UI、HTTP client、SSE client 和 Tailwind/ESLint/TypeScript 配置。
- Shared package：由 FastAPI OpenAPI 生成的 TypeScript API Schema。
- Documentation：Architecture Baseline、Bootstrap Specification、Implementation Report、Repository Tree 和 Test Results。

完整文件清单参见 [Repository Tree v0.1](repository-tree-v0.1.md)。

## 2. Architecture decisions implemented

- Workflow First, Agent Second：本轮没有创建任何具体 Agent。
- Frontend 只连接 Banking Application HTTP/SSE API，不连接 Agent implementation。
- Domain Model 不依赖 LangGraph、LangChain 或其他 Agent Framework。
- Conversation、Message、Task、Event 是显式结构化状态；Task 状态真实持久化。
- Server State Authoritative：Frontend 收到 SSE 后重新 GET Conversation/Tasks，不在本地推演最终状态。
- Default Deny：ToolRegistry 为空，PolicyService 对未知能力返回 `DENY`。
- Modular Monolith：API、runtime、policy、MockBank 均位于同一 Backend Application。
- Event 先持久化，再通过单进程 EventBus 实时发布；SSE 不是事实来源。
- DevPrincipal 通过 FastAPI dependency 注入固定用户 `dev-user-001`。
- BootstrapRuntime 是确定性、无 LLM、可直接替换的临时 runtime。

## 3. Database tables created

Alembic migration `0001_bootstrap` 在 PostgreSQL 创建：

1. `conversations`
2. `messages`
3. `tasks`
4. `events`

另有 Alembic 自身的 `alembic_version` 表。Workflow、Approval、Operation 只有 Pydantic Domain Schema，没有数据库表。

`events.sequence` 是数据库生成的全局递增 sequence。Task 每次状态迁移执行 `version += 1`。

## 4. API endpoints implemented

| Method | Endpoint | Purpose |
| --- | --- | --- |
| GET | `/health` | Health check |
| GET | `/api/v1/conversations` | 当前用户 Conversation 列表 |
| POST | `/api/v1/conversations` | 创建 Conversation |
| GET | `/api/v1/conversations/{conversation_id}` | Conversation 和 Messages |
| POST | `/api/v1/conversations/{conversation_id}/messages` | 持久化 User Message 并创建 Task，返回 202 |
| GET | `/api/v1/tasks` | Task 列表，可按 Conversation 过滤 |
| GET | `/api/v1/tasks/{task_id}` | 获取 Task authoritative state |
| GET | `/api/v1/events?conversation_id=...` | Conversation SSE stream |

没有 `/agents/*`、`/skills/*`、Transfer、Investment、Card Write 或 Subscription Cancellation API。

## 5. SSE event types implemented

- `conversation.message.created`
- `task.created`
- `task.started`
- `task.completed`
- `task.failed`
- `conversation.message.completed`

Event envelope 包含 event_id、event_type、timestamp、conversation_id、task_id、sequence 和 data。

真实 Docker 验收中，单次 `Hello` 请求按 sequence 1–5 收到：

```text
conversation.message.created
task.created       status=PENDING   version=1
task.started       status=RUNNING   version=2
task.completed     status=COMPLETED version=3
conversation.message.completed
```

## 6. Tests added

- `test_health.py`：Health 200。
- `test_conversations.py`：Conversation persistence、Message persistence、Task creation、Assistant Message。
- `test_tasks.py`：COMPLETED transition/version 和受控 FAILED transition/error。
- `test_events.py`：Event persistence、sequence ordering 和 live EventBus delivery。
- `conftest.py`：独立 async SQLite test database 和 FastAPI dependency override。

## 7. Test/build results

最新结果记录在 [Test Results v0.1](test-results-v0.1.md)。摘要：

- Ruff：通过。
- Pytest：`7 passed`。
- Frontend ESLint：通过。
- TypeScript typecheck：通过。
- Next.js production build：通过。
- OpenAPI TypeScript generation：通过，生成 540 行 Schema。
- `docker compose up --build -d`：通过。
- PostgreSQL healthcheck：healthy。
- API `/health`：200，`{"status":"ok"}`。
- Web `/`：200。
- Browser UI + SSE + Task update：通过，console errors 为 0。
- API 容器重建后持久化恢复：通过。

## 8. Known limitations

- BootstrapRuntime 不是真正 Agent Runtime，也没有 LLM 或 Tool Calling。
- EventBus 仅在单进程内实时 fan-out。
- SSE 没有 `Last-Event-ID` replay；Frontend 通过 Resource API 恢复状态。
- Authentication 仅为固定 DevPrincipal。
- 没有 Background Worker；runtime 工作依附 API 进程。
- Backend automated tests 使用 async SQLite；PostgreSQL migration 和端到端流程通过 Docker 另行实测。
- 没有真实 Banking API、Approval execution、Operation execution 或具体 Workflow。

## 9. Deviations from specification

Deviations: None.

测试数据库使用 SQLite 是测试隔离策略，不改变生产 PostgreSQL、asyncpg 和 Alembic 架构。生产 Compose 已在真实 PostgreSQL 17 上完成验证。

## 10. Architecture questions discovered

Architecture Questions: None.

Bootstrap 已在规定边界停止，没有进入 Minimal Agent Runtime、FinancialAnalysisAgent、LangGraph、MonthlyReportSkill 或 TransferWorkflow。

