# AI Banking Agent

注意：产品主要面向的是中文用户，description 和 前端页面以中文为主。

当前版本已完成 `03.4 Report Artifact + Structured UI v0.3.4`。用户可以在同一个 `BANKING_REQUEST` 中请求月度消费报告：FinancialAnalysisAgent 只通过确定性 Financial Tools 生成 Snapshot，已注册的 MonthlySpendingReportSkill 构建报告，后端持久化不可变 Report Artifact，前端通过 Reports API 展示结构化报告并支持刷新恢复。

当前交付文档：

- [Implementation Report v0.3.4](docs/implementation-report-v0.3.4.md)
- [Repository Tree v0.3.4](docs/repository-tree-v0.3.4.md)
- [Test Results v0.3.4](docs/test-results-v0.3.4.md)

历史文档：

- [Implementation Report v0.3.3](docs/implementation-report-v0.3.3.md)
- [Repository Tree v0.3.3](docs/repository-tree-v0.3.3.md)
- [Test Results v0.3.3](docs/test-results-v0.3.3.md)
- [Golden Monthly Report v0.3.3](docs/golden-monthly-report-v0.3.3.md)

- [Implementation Report v0.3.2](docs/implementation-report-v0.3.2.md)
- [Repository Tree v0.3.2](docs/repository-tree-v0.3.2.md)
- [Test Results v0.3.2](docs/test-results-v0.3.2.md)
- [Golden Financial Data v0.3.2](docs/golden-financial-data-v0.3.2.md)

- [Implementation Report v0.3.1](docs/implementation-report-v0.3.1.md)
- [Repository Tree v0.3.1](docs/repository-tree-v0.3.1.md)
- [Test Results v0.3.1](docs/test-results-v0.3.1.md)
- [Golden Financial Data v0.3.1](docs/golden-financial-data-v0.3.1.md)

- [Implementation Report v0.2.2](docs/implementation-report-v0.2.2.md)
- [Repository Tree v0.2.2](docs/repository-tree-v0.2.2.md)
- [Test Results v0.2.2](docs/test-results-v0.2.2.md)
- [Runtime Comparison v0.2.2](docs/runtime-comparison-v0.2.2.md)
- [Testing Guide v0.2](docs/testing-guide-v0.2.md)

## Runtime 架构

```text
User Message → RequestRouter → AgentRegistry
                              ├─ agent:minimal-banking
                              ├─ agent:financial-analysis
                              └─ UNSUPPORTED (direct capability notice)
                                        │
                              LangGraphAgentRuntime
                                        │
                     ToolRegistry → PolicyService → ToolExecutor
                                      /             \
                       account handlers    FinancialAnalyticsService
                                  \            /
                                  MockBankService

LangGraph only: PostgreSQL Checkpointer (thread_id = task_id)
Domain DB: Conversation / Message / Task(requested_output/executor/output) / Report / Event
```

LangGraph 只替换 Agent loop 的 state/routing/checkpoint orchestration，不替换 `LLMProvider`、工具权限、Domain Task、Conversation、Event/Audit 或 MockBankService。Checkpoint 表由 LangGraph 包的 `setup()` 管理；Application tables 由 Alembic 管理。

当前 Registry 注册：

- `account.list` / `list_accounts`
- `account.get_balance` / `get_balance`

两者都是 `R1_PRIVATE_READ`、无副作用。`account.list` 允许 `agent:minimal-banking` 和 `agent:financial-analysis`，便于后者将“工资卡”等用户语义解析为内部 `account_id`；`account.get_balance` 仍只允许 `agent:minimal-banking`。不存在转账写操作、raw transaction search、收款人或订阅 Tool。

财务分析 Capability 为：

- `transaction.spending_summary` / `get_spending_summary`
- `transaction.category_breakdown` / `get_category_breakdown`
- `transaction.compare_periods` / `compare_spending_periods`
- `transaction.top_transactions` / `get_top_transactions`

它们同样是 `R1_PRIVATE_READ`、无副作用，且只允许 `agent:financial-analysis`。FinancialAnalysisAgent 额外可使用 `account.list` 解析用户说的卡名，但不能调用 `account.get_balance`。`agent:minimal-banking` 的 capability allowlist 没有扩大，因此看不到且无法调用四个 financial Tool。本轮没有 `transaction.search`。

## Financial analytics boundary

金额、分类汇总、环比和排名均由 Python `Decimal` 确定性计算。有效交易 status 显式固定为 `POSTED`；Spending 仅包含已入账 `DEBIT` 且排除 `TRANSFER`；Income 仅包含已入账 `CREDIT` 且同样排除 `TRANSFER`。月份使用 `YYYY-MM` 自然月的左闭右开区间。不做汇率换算，同次聚合出现多币种会返回 `MIXED_CURRENCY_UNSUPPORTED`。

> Financial Agents should receive deterministic summaries by default, not full transaction history.

四个 Tool 只返回聚合结果或 `1..20` 条 Top N，不向 LLM 暴露整月 raw transaction history。

## Monthly spending report boundary

`skill:monthly-spending-report` version `1` 是当前唯一注册的 Skill，执行路径为：

```text
FinancialAnalysisSnapshot
    → deterministic report core + ReportFormatter
    → LLM headline / insights (tools=[])
    → Pydantic + evidence + numeric-leak validation
    → MonthlySpendingReport
```

Skill 不接受 raw transactions、Conversation history 或自然语言交易列表，也不调用任何 Tool。金额、占比、环比、排序和展示四舍五入均由 Python 处理，原始 `Decimal` 值在报告中保留。缺少 comparison 或 Top N 时会显式标记 `PARTIAL`；缺少 summary、category 或必要 tool evidence 时 fail closed。

报告请求的产品路径为：

```text
RequestRouter(FINANCIAL_ANALYSIS / MONTHLY_REPORT)
    → FinancialAnalysisAgent
    → FinancialAnalysisSnapshot
    → SkillRegistry / SkillExecutor
    → immutable Report
    → GET /api/v1/reports[/report_id]
    → structured Reports UI
```

Report 使用 `source_task_id + report_type + report_version` 强幂等，保存 Skill 执行当时的完整内容、Skill 版本和 canonical Snapshot SHA-256。API 只支持按当前用户 GET 列表/详情，不提供 POST、PATCH、PUT 或 DELETE。所有精确 `Decimal` 以 JSON string 暴露；前端直接使用 Backend `*_display` 字段，不重新计算或四舍五入。

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

脚本覆盖账户列表、工资卡余额、写权限注入和不存在账户，不输出 API Key。

v0.3.2 Router + Specialist Agent 真实 Provider smoke：

```bash
LANGGRAPH_CHECKPOINT_DATABASE_URL=postgresql://banking:banking@localhost:5432/banking \
  uv run --project apps/api python scripts/smoke_routing.py
```

该脚本覆盖账户列表、8 月全账户消费分析和工资卡过滤分析；只输出脱敏路由、Tool evidence 摘要和用户回答，不输出 API Key 或 Chain-of-Thought。

v0.3.3 MonthlySpendingReportSkill 真实 Provider smoke：

```bash
uv run --project apps/api python scripts/smoke_monthly_report_skill.py
```

该脚本使用 committed Golden Snapshot，验证 deterministic core 全等、narrative grounding、无 Tool Call 与无数字泄漏。

v0.3.4 完整 Report 产品链路真实 Provider smoke：

```bash
DATABASE_URL=postgresql+asyncpg://banking:banking@localhost:5432/banking \
LANGGRAPH_CHECKPOINT_DATABASE_URL=postgresql://banking:banking@localhost:5432/banking \
  uv run --project apps/api python scripts/smoke_report_product.py
```

该脚本验证 `FINANCIAL_ANALYSIS / MONTHLY_REPORT` 路由、四个确定性 Financial Tool、Skill Registry、Report 持久化、Reports GET API、Golden core 全等和单一用户确认消息。

前端验证：

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

当前不实现 Chart、PDF/Excel/邮件导出、定时报告、Report 编辑/删除、raw transaction search、anomaly detection、Memory、RAG、MCP、Planner、Agent-to-Agent 调用或任何写操作。
