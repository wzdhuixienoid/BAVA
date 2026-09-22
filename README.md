# AI Banking Agent

当前版本已完成 `02.2 LangGraph Refactor & Runtime Hardening v0.2.2`。系统同时保留 `ManualAgentRuntime` 和直接基于 `StateGraph` 的 `LangGraphAgentRuntime`，两者共用 Provider、ContextBuilder、Tool Registry、Policy 和 ToolExecutor。业务能力仍只有账户列表和余额查询。

交付文档：

- [Implementation Report v0.2.2](docs/implementation-report-v0.2.2.md)
- [Repository Tree v0.2.2](docs/repository-tree-v0.2.2.md)
- [Test Results v0.2.2](docs/test-results-v0.2.2.md)
- [Runtime Comparison v0.2.2](docs/runtime-comparison-v0.2.2.md)
- [Testing Guide v0.2](docs/testing-guide-v0.2.md)

## Runtime 架构

```text
                       TaskRunner
                           │
                    RuntimeFactory
                    /            \
       ManualAgentRuntime    LangGraphAgentRuntime
                    \            /
                     LLMProvider
                           │
                     ToolExecutor
                           │
                     PolicyService
                           │
                      ToolRegistry
                           │
                    MockBankService

LangGraph only: PostgreSQL Checkpointer (thread_id = task_id)
Domain DB: Conversation / Message / Task / Event
```

LangGraph 只替换 Agent loop 的 state/routing/checkpoint orchestration，不替换 `LLMProvider`、工具权限、Domain Task、Conversation、Event/Audit 或 MockBankService。Checkpoint 表由 LangGraph 包的 `setup()` 管理；Application tables 由 Alembic 管理。

当前 Registry 仍仅注册：

- `account.list` / `list_accounts`
- `account.get_balance` / `get_balance`

两者都是 `R1_PRIVATE_READ`、无副作用，且只允许 `agent:minimal-banking`。不存在转账、交易查询、收款人或订阅 Tool。

## 配置

```bash
cp .env.example .env
```

```env
LLM_PROVIDER=openai_compatible
LLM_BASE_URL=
LLM_API_KEY=
LLM_MODEL=
LLM_TIMEOUT_SECONDS=30

AGENT_MAX_STEPS=6
AGENT_MAX_TOOL_CALLS=4
AGENT_RUNTIME=langgraph

LANGGRAPH_CHECKPOINT_DATABASE_URL=
LANGGRAPH_STRICT_MSGPACK=true
```

`LLM_BASE_URL` 的唯一语义是 OpenAI-compatible API root，例如 `https://example.com/v1`。Adapter 追加 `/chat/completions`；直接配置完整 endpoint 会报错。`LLM_API_KEY` 不进入数据库、Event、Prompt、日志或前端。

`AGENT_RUNTIME` 可设为 `manual` 或 `langgraph`。Task 创建时会将当次 backend 写入 `runtime_backend`，执行途中不重新选择。`LANGGRAPH_CHECKPOINT_DATABASE_URL` 为 psycopg PostgreSQL URL；留空时使用 Application `DATABASE_URL` 并自动去掉 SQLAlchemy driver 后缀。

## 启动

```bash
docker compose up --build
```

- Web：`http://localhost:3000`
- API：`http://localhost:8000`
- OpenAPI：`http://localhost:8000/docs`

API 启动次序是：Alembic migration → LangGraph checkpoint `setup()` → stale Task reconciliation → 接收请求。上一个进程留下的 `PENDING/RUNNING` Task 会转为 `INTERRUPTED`，不会自动恢复业务执行。

本地开发：

```bash
cd apps/api
uv sync
uv run alembic upgrade head
uv run uvicorn banking_api.main:app --reload
```

## 测试

默认 suite 使用 FakeProvider 和 SQLite，不访问互联网：

```bash
cd apps/api
uv run ruff check src tests ../../scripts
uv run pytest
```

PostgreSQL integration 必须使用库名包含 `test` 的隔离数据库：

```bash
cd apps/api
TEST_DATABASE_URL=postgresql+asyncpg://banking:banking@localhost:5432/banking_test \
  uv run pytest -m postgres
```

真实 Provider smoke：

```bash
AGENT_RUNTIME=manual make agent-smoke
AGENT_RUNTIME=langgraph \
LANGGRAPH_CHECKPOINT_DATABASE_URL=postgresql://banking:banking@localhost:5432/banking \
make agent-smoke
```

脚本覆盖账户列表、工资卡余额、写权限注入和不存在账户，不输出 API Key。前端验证：

```bash
pnpm web:lint
pnpm web:typecheck
pnpm web:build
```

## API、Event 与安全语义

消息提交返回 `202`，`InProcessTaskRunner` 使用独立 DB session 执行。开发 Trace：

```http
GET /api/v1/tasks/{task_id}/events
```

Trace 显示 `runtime_backend`、`checkpoint_enabled`、LLM step 和脱敏 Tool metadata，不返回 raw checkpoint、Prompt dump 或 Chain-of-Thought。参数校验错误是 recoverable；未知工具、越权、输出校验错误和执行失败都是 fatal，权限拒绝不会交给模型“修正”。

`02.2 realtime event transport currently assumes a single API process.`

当前不实现 Retry/Resume Task API、Human-in-the-loop、FinancialAnalysisAgent、Transaction Tool、Memory、RAG、MCP、Redis、Celery、Multi-Agent 或任何写操作。
