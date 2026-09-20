# AI Banking Agent

当前版本实现 `02.1 Minimal Agent Runtime Specification v0.2` 的真实 LLM 调用之前部分：Provider-neutral LLM 边界、确定性 Fake Provider、手写 Agent Loop、两个只读银行 Tool、Synthetic Banking Dataset、Policy、持久化 Task/Event、SSE 和前端任务进度。

历史架构基线仍见 [Bootstrap Architecture Baseline v0.1](docs/architecture-baseline-v0.1.md)。本轮交付记录见 [Implementation Report v0.2](docs/implementation-report-v0.2.md)，体验与底层观察步骤见 [Testing Guide v0.2](docs/testing-guide-v0.2.md)。

## Runtime 链路

```text
User Message → ContextBuilder → LLMProvider
                                  ├─ Final Answer
                                  └─ Tool Call
                                      ↓
                     ToolRegistry → PolicyService → ToolExecutor
                                      ↓
                               MockBankService
                                      ↓
                       Tool Result → LLM → Answer
```

Runtime 不依赖供应商 SDK 类型。`OpenAICompatibleProvider` 是唯一理解 OpenAI-compatible wire format 的模块；`AgentRuntime`、`ContextBuilder` 和 Tool 层只使用项目内部的 LLM 模型。

当前仅注册：

- `account.list` / `list_accounts`
- `account.get_balance` / `get_balance`

两者均为 `R1_PRIVATE_READ`、无副作用，且只允许 `agent:minimal-banking`。项目没有转账、交易查询、收款人或订阅 Tool。

## 配置

复制环境模板：

```bash
cp .env.example .env
```

LLM 使用统一配置：

```env
LLM_PROVIDER=openai_compatible
LLM_BASE_URL=
LLM_API_KEY=
LLM_MODEL=
LLM_TIMEOUT_SECONDS=30
AGENT_MAX_STEPS=6
AGENT_MAX_TOOL_CALLS=4
```

Backend 不读取 `OPENAI_API_KEY` 或 `OPENAI_MODEL`。`LLM_API_KEY` 只进入 Provider 的 Authorization header，不进入数据库、Event、Prompt、日志或前端。

## 启动

完整容器环境：

```bash
docker compose up --build
```

- Web：`http://localhost:3000`
- API：`http://localhost:8000`
- OpenAPI：`http://localhost:8000/docs`

API 容器启动时自动执行 Alembic migration。

本地开发：

```bash
cd apps/api
uv sync
uv run alembic upgrade head
uv run uvicorn banking_api.main:app --reload
```

另一个终端：

```bash
pnpm install
pnpm web:dev
```

## 数据与验证

完全虚构、固定的数据位于 `apps/api/src/banking_api/mock_bank/data/`。生成和验证命令：

```bash
cd apps/api
uv run python ../../scripts/generate_mock_data.py
uv run python ../../scripts/validate_mock_data.py
```

默认测试不访问互联网或真实 LLM：

```bash
cd apps/api
uv run ruff check src tests ../../scripts
uv run pytest
```

PostgreSQL 集成测试必须显式提供隔离测试库，且数据库名必须包含 `test`：

```bash
cd apps/api
TEST_DATABASE_URL=postgresql+asyncpg://banking:banking@localhost:5432/banking_test \
  uv run pytest -m postgres
```

前端验证：

```bash
pnpm web:lint
pnpm web:typecheck
pnpm web:build
```

真实 DeepSeek function-calling 已完成验证。显式重跑 smoke（不会输出 API Key）：

```bash
make agent-smoke
```

该脚本覆盖账户列表、工资卡余额、写权限注入和不存在账户四个场景。它不会被默认 pytest 调用。

## API 与事件

消息提交仍返回 `202`，创建 `MINIMAL_AGENT_RUN` 后交给 `InProcessTaskRunner` 使用独立 DB session 执行。开发期 sanitized trace：

```http
GET /api/v1/tasks/{task_id}/events
```

持久化产品事件包括 `task.created/started/progress/completed/failed` 和 `conversation.message.completed`；内部可观测事件包括 `agent.run.*`、`llm.request.*`、`tool.call.*`。事件不保存 Prompt dump、Chain-of-Thought、API Key、余额或完整 Tool Result。

`02.1 realtime event transport currently assumes a single API process.`

当前不得启用多 worker；实时 EventBus 只做单进程 fan-out，PostgreSQL Event 才是持久事实。

## 当前边界

- OpenAI-compatible adapter 的自建 HTTP client 不继承系统代理变量；连接目标完全由 `LLM_BASE_URL` 决定。
- Authentication 仍是固定开发身份。
- Task 在 API 进程内异步运行，进程退出后暂不恢复未完成任务。
- SSE 暂未实现 `Last-Event-ID` replay，前端通过资源 API 恢复状态。
- 没有 Agent Framework、LangGraph、LangChain、MCP、RAG、Vector DB、Redis 或 Celery。
- 不实现 FinancialAnalysisAgent、Transaction Tool、Memory 或任何写操作。
