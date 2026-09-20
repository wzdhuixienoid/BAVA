# AI Banking Agent

Iteration 0 是面向未来 Banking Agent 的应用骨架。它不使用 LLM 或 Agent 框架，当前目标是验证一条完整、可持久化、可测试的链路：浏览器 → API → 数据库 → 确定性运行时 → SSE → 浏览器。

冻结的设计说明位于：[架构基线 v0.1](docs/architecture-baseline-v0.1.md) 和 [Codex Bootstrap 规格 v0.1](docs/codex-bootstrap-v0.1.md)。

交付与验收记录：

- [Implementation Report v0.1](docs/implementation-report-v0.1.md)
- [Repository Tree v0.1](docs/repository-tree-v0.1.md)
- [Test Results v0.1](docs/test-results-v0.1.md)

## 系统架构

```text
Next.js UI ── HTTP/SSE ── FastAPI 模块化单体 ── PostgreSQL
                              │
                              ├─ ConversationService
                              ├─ TaskService
                              ├─ 确定性 BootstrapRuntime
                              └─ 持久化 Event + 进程内实时传输
```

Frontend 只展示服务器拥有的 Conversation、Message 和 Task 状态。SSE 只是实时通知通道；连接中断或页面刷新后，Frontend 会通过资源 API 恢复状态。Bootstrap Runtime 是临时且可替换的确定性运行时，不是 Agent。

## 产品语言

产品面向中国用户，用户可见界面、系统回复和错误提示默认使用中文。API 字段名、Event type、Task type 和状态枚举继续使用稳定的英文机器标识，Frontend 负责显示对应的中文名称。

## 环境要求

- 完整容器环境：Docker 和 Docker Compose
- 本地开发：PostgreSQL 15+
- Python 3.12+ 和 [uv](https://docs.astral.sh/uv/)
- Node.js 22+ 和 pnpm 11+

## 启动完整应用

```bash
cp .env.example .env
docker compose up --build
```

启动后：

- Web：`http://localhost:3000`
- API：`http://localhost:8000`
- OpenAPI：`http://localhost:8000/docs`

API 容器会在启动 FastAPI 前自动执行 Alembic migration。

完整 Compose 构建与启动流程已使用 Docker Engine 29.8 和 Docker Compose 5.5 完成验证。

## 本地开发

本地运行时，请在 `.env` 中使用指向 `localhost` 的 PostgreSQL URL，不要使用 Compose 内部服务名 `postgres`。

启动 Backend：

```bash
cd apps/api
uv sync
uv run alembic upgrade head
uv run uvicorn banking_api.main:app --reload
```

在另一个终端启动 Frontend：

```bash
pnpm install
pnpm web:dev
```

## 数据库 Migration

```bash
cd apps/api
uv run alembic upgrade head
```

Iteration 0 只创建四张应用表：`conversations`、`messages`、`tasks` 和 `events`，除此之外只有 Alembic 自己的版本表。

## 测试与验证

```bash
cd apps/api
uv run ruff check .
uv run pytest

cd ../..
pnpm web:lint
pnpm web:typecheck
pnpm web:build
```

Backend 测试使用隔离的异步 SQLite 数据库，以便快速验证 Repository、Application Service 和 API；生产环境及 Docker Compose 使用 PostgreSQL 和 `asyncpg`。

## 生成 Frontend API 类型

先在 8000 端口启动 FastAPI，然后运行：

```bash
pnpm api:generate
```

该命令读取 `/openapi.json`，并重新生成 `packages/api-client/src/schema.d.ts`。Pydantic Schema 是 API 类型的唯一事实来源，Frontend 直接导入生成的类型，不长期维护重复 Schema。

## Iteration 0 已实现内容

- 通过 Dependency 注入固定开发用户 `dev-user-001`
- 持久化 Conversation、Message、Task 和 Event
- Message 提交与确定性的 `BOOTSTRAP_MESSAGE_PROCESSING`
- Task 状态转换 `PENDING → RUNNING → COMPLETED`，以及受控 `FAILED`
- 全局递增、持久化的 Event sequence
- 带 keep-alive、按 Conversation 过滤的 SSE
- Conversation、Message、Task 工作区和断线恢复
- 空的 Agent、Skill、Workflow、Tool Registry
- 默认拒绝的 PolicyService、ContextBuilder 边界和只读 MockBankService
- 不进入数据库、不执行的 Workflow、Approval、Operation Schema

## 当前限制

- `BootstrapRuntime` 是临时确定性基础设施，不是真正的 Agent Runtime。
- 实时 EventBus 仅在单进程内工作；PostgreSQL Event 是持久事实，实时 fan-out 不是分布式的。
- SSE 尚未实现 `Last-Event-ID` replay；客户端通过 GET API 恢复资源状态。
- Authentication 只是固定开发身份。
- 没有 Background Worker；Bootstrap Runtime 依附于 API 进程执行。

当前明确没有实现：LLM 调用、LangGraph/LangChain、MCP、RAG、Embedding、Vector Database、Redis、Worker、真实银行 API、真实认证、Approval、Operation、具体 Workflow、Agent 或可执行 Skill。系统中不存在转账、投资购买、冻结银行卡或取消订阅的 API/Tool。
