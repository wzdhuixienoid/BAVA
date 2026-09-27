# AI Banking Agent

当前版本：`v0.5.3`

面向中文用户的个人银行 Agent 应用。当前产品可以查询账户与余额、分析月度消费、生成结构化报告，以及通过持久化 Transfer Workflow 完成草稿、校验、审批、重新认证、幂等提交和 Provider 最终状态确认。只有 `Operation SUCCEEDED` 表示资金已被 Mock Provider 确认转出。

核心设计原则：金融金额、分类汇总、占比、排名和环比全部由确定性 Python `Decimal` 代码计算；LLM 只负责意图识别、工具选择和基于可信事实的自然语言解释。

## 当前能力

| 用户需求 | 执行者 | 能力 |
|---|---|---|
| 查看账户、查询余额 | `agent:minimal-banking` | `account.list`、`account.get_balance` |
| 月度支出、分类、环比、主要交易分析 | `agent:financial-analysis` | 四个只读 Financial Tools |
| 生成月度消费报告 | Financial Agent + `skill:monthly-spending-report` | Snapshot → immutable Report Artifact |
| 转账全链路 | `workflow:transfer` | Draft → Validation → Approval → Reauthentication → Operation → Verification |
| Operation 自动恢复 | PostgreSQL-backed recovery worker | due scan → `SKIP LOCKED` claim → lease → reconcile → retry/terminal |
| 并发转账资金安全 | `MockTransferProvider` | account-scoped advisory lock → authoritative balance → atomic ledger fact |
| 持久事件发布 | Transactional Outbox | Event + Outbox atomic commit → leased publisher → EventBus/SSE |

```text
Financial Analysis Vertical Slice: COMPLETE
Transfer Vertical Slice: COMPLETE
Durable Operation Recovery: COMPLETE
Cross-Process Financial Concurrency: COMPLETE
Transactional Outbox: COMPLETE
```

用户可以直接输入：

```text
我有哪些账户？
工资卡余额多少？
为什么2026年8月花这么多？
分析一下工资卡2026年8月的消费
生成一份2026年8月份消费报告
```

报告生成后可在 Conversation 中通过 ReportCard 打开，也可以从 `/reports` 查看历史报告。

## 架构

```text
User Message
    → RequestRouter
    → AgentRegistry / TransferWorkflow
        ├─ MinimalBankingAgent
        └─ FinancialAnalysisAgent
    → LangGraphAgentRuntime
    → ToolRegistry → PolicyService → ToolExecutor
        └─ transfer.commit (R4) / transfer.get_status (R1)
    → persistent Operation → MockTransferProvider idempotency ledger
        → PostgreSQL account advisory lock → authoritative balance decision
    → PostgreSQL claim/lease → automatic Operation recovery
    → durable Event + Outbox intent → OutboxPublisher → EventBus/SSE
    → FinancialAnalysisSnapshot
    → SkillRegistry → MonthlySpendingReportSkill
    → immutable Report Artifact
    → Reports API
    → Structured Web UI
```

持久化职责分离：

- Alembic 管理 Conversation、Message、Task、Event 和 Report 等应用表。
- LangGraph PostgreSQL Checkpointer 管理 Agent runtime checkpoint。
- committed Mock Bank synthetic data 作为基线 fixture；工资卡等有效余额会减去持久化 provider ledger 中已成功的转出，不修改 committed JSON。
- Mock Provider 在自己的短 PostgreSQL transaction 内按 source account 串行化，重新计算 fixture balance 减成功 ledger 的 authoritative balance，然后原子地接受或拒绝转账。
- Operation recovery 调度、尝试次数和 lease 同样持久化在 Application PostgreSQL；LangGraph checkpoint 不是 Workflow/Operation 业务事实源。
- 所有需实时通知的 durable Event 都与唯一 Outbox intent 在同一业务 transaction 内写入；Outbox 只引用 Event identity，不复制 payload。

产品 Runtime 是 `LangGraphAgentRuntime`。`ManualAgentRuntime` 仅作为 reference 保留，不承载新功能。

## 设计基线：新增功能前必读

[Architecture Baseline v0.1](docs/architecture-baseline-v0.1.md) 定义了本项目长期遵守的 Agent Engineering 方向。它不是过期的实现清单，而是防止功能演进偏离整体设计的架构基线。

核心原则包括：

- Workflow First, Agent Second：能确定性完成的业务不强行 Agent 化。
- LLM ≠ Business System：LLM 负责理解与选择，业务系统负责事实和执行。
- Structured State > Conversation：业务事实进入结构化状态，不依赖聊天文本。
- Default Deny 与 Least Privilege：Agent、Skill、Workflow、Tool 只获得最小必要权限。
- Domain API > Agent API：前端面向 Banking Application，不直接耦合 Agent Runtime。
- Structured handoff：组件之间传 typed result，不传隐藏推理或 Chain-of-Thought。
- Modular Monolith First：在真实扩展问题出现前不引入不必要的分布式复杂度。

新增功能在实现前必须先判断它属于哪一类执行概念：

| 概念 | 负责的问题 |
|---|---|
| Agent | 现在应该做什么？ |
| Skill | 这类任务怎样专业、稳定地完成？ |
| Workflow | 这件事必须按照什么状态和规则完成？ |
| Tool | 系统具体能够做什么？ |

设计评审至少检查：确定性逻辑是否误放进 LLM、状态是否结构化、权限是否最小、是否绕过 Policy/Registry/Domain API，以及是否为了技术展示引入尚未需要的 Planner、RAG、MCP 或 Multi-Agent。

当前实现按该基线渐进建设，并不代表基线中所有未来组件已经实现。若新需求需要改变基线原则或执行边界，应先更新设计文档并记录偏差与理由，再修改代码，不能静默偏离。

## 可信金融数据边界

- 金额统一使用 `Decimal`，禁止使用 `float` 进行金融计算。
- 月份使用 `YYYY-MM`，范围为自然月左闭右开区间。
- 有效交易 status 显式为 `POSTED`。
- Spending 是 `POSTED + DEBIT + category != TRANSFER`。
- Income 是 `POSTED + CREDIT + category != TRANSFER`。
- 不做汇率换算；同次聚合出现多币种时返回 `MIXED_CURRENCY_UNSUPPORTED`。
- Financial Tools 只返回聚合结果或 bounded Top N，不向 LLM 提供整月 raw transaction history。
- Report exact Decimal 在 JSON 中序列化为 string；前端直接使用 Backend `*_display`，不重新计算或四舍五入。

> Financial Agents should receive deterministic summaries by default, not full transaction history.

## 权限边界

默认仍是只读和最小权限；唯一例外是 04.3 新增的受控资金提交能力。

- `agent:minimal-banking`：允许 `account.list`、`account.get_balance`。
- `agent:financial-analysis`：允许 `account.list` 和四个 Financial Tools，不允许余额、转账、卡片或其他写能力。
- `skill:monthly-spending-report`：`allowed_tools=[]`，只能消费 `FinancialAnalysisSnapshot`。
- `workflow:transfer`：允许三项 R1 读能力，以及仅接受持久化 `operation_id` 的 `transfer.commit` (`R4_FINANCIAL_COMMIT`) 和 `transfer.get_status` (R1)。
- Recovery worker 不是新的 Tool caller，也不扩大 `transfer.commit` allowlist；它只能 claim 已有 Operation，并调用与手工 reconcile 相同的 `OperationService` 状态转移。
- 任何 Agent 或 Skill 都看不到、也无权调用 `transfer.commit`；LLM 在意图提取后完全退出执行路径。
- Reports API 只有 GET list/detail，没有 POST、PUT、PATCH 或 DELETE。

Router 只选择 Agent/Workflow 和 requested output，不扩大权限。未知 Tool、越权调用和写操作请求均 fail closed。

## 快速启动

准备配置：

```bash
cp .env.example .env
```

至少填写 OpenAI-compatible Provider：

```env
LLM_PROVIDER=openai_compatible
LLM_BASE_URL=https://example.com/v1
LLM_API_KEY=
LLM_MODEL=
```

`LLM_BASE_URL` 必须是 API root，Adapter 会追加 `/chat/completions`。密钥不会进入数据库、Event、Prompt trace 或前端。

启动完整产品：

```bash
docker compose up --build
```

- Web：<http://localhost:3000>
- Reports：<http://localhost:3000/reports>
- API：<http://localhost:8000>
- OpenAPI：<http://localhost:8000/docs>

API 启动时依次执行 Alembic migration、LangGraph checkpoint setup、stale Task reconciliation，然后启动 Operation recovery loop 和 Outbox publisher。关闭时两个专用 worker 都会停止并等待当前轮询结束。

Recovery 通过环境变量配置：

```env
OPERATION_RECOVERY_ENABLED=true
OPERATION_RECOVERY_POLL_INTERVAL_SECONDS=5
OPERATION_RECOVERY_LEASE_SECONDS=60
OPERATION_RECOVERY_INITIAL_RETRY_SECONDS=5
OPERATION_RECOVERY_MAX_RETRY_SECONDS=300
OPERATION_RECOVERY_BACKOFF_MULTIPLIER=2
OPERATION_RECOVERY_BATCH_SIZE=10
```

Outbox 通过环境变量配置：

```env
OUTBOX_PUBLISHER_ENABLED=true
OUTBOX_PUBLISHER_POLL_INTERVAL_SECONDS=0.5
OUTBOX_PUBLISHER_LEASE_SECONDS=30
OUTBOX_PUBLISHER_INITIAL_RETRY_SECONDS=1
OUTBOX_PUBLISHER_MAX_RETRY_SECONDS=60
OUTBOX_PUBLISHER_BACKOFF_MULTIPLIER=2
OUTBOX_PUBLISHER_BATCH_SIZE=20
```

## 本地开发

Backend：

```bash
cd apps/api
uv sync
uv run alembic upgrade head
uv run uvicorn banking_api.main:app --reload
```

Frontend：

```bash
pnpm install
pnpm web:dev
```

常用验证：

```bash
cd apps/api
uv run ruff check . ../../scripts
uv run pytest
```

```bash
pnpm api:generate
pnpm web:lint
pnpm web:typecheck
pnpm web:build
```

PostgreSQL integration 必须使用库名包含 `test` 的隔离数据库：

```bash
cd apps/api
TEST_DATABASE_URL=postgresql+asyncpg://banking:banking@localhost:5432/banking_test \
  uv run pytest -m postgres
```

真实 Provider 的完整报告链路 smoke：

```bash
DATABASE_URL=postgresql+asyncpg://banking:banking@localhost:5432/banking \
LANGGRAPH_CHECKPOINT_DATABASE_URL=postgresql://banking:banking@localhost:5432/banking \
  uv run --project apps/api python scripts/smoke_report_product.py
```

Smoke 验证 Router、Financial Agent、确定性工具、Skill、Report persistence、GET API、Golden core 和单一用户确认消息；不会输出 API Key 或 Chain-of-Thought。

## 主要 API 与页面

```text
POST /api/v1/conversations/{conversation_id}/messages
GET  /api/v1/tasks/{task_id}
GET  /api/v1/tasks/{task_id}/events
GET  /api/v1/reports
GET  /api/v1/reports/{report_id}
GET  /api/v1/workflows/{workflow_id}
GET  /api/v1/workflows?conversation_id=...
POST /api/v1/workflows/{workflow_id}/actions/{set-recipient-query|select-payee|select-source-account|set-amount|approve|start-reauth|verify-reauth|commit|cancel}
GET  /api/v1/operations/{operation_id}
POST /api/v1/operations/{operation_id}/actions/reconcile
```

```text
/                    Conversation Workspace
/reports             Report history
/reports/{reportId}  Structured monthly report
```

SSE 用于实时通知；Task、Report 和 Workflow API 始终是页面刷新恢复的 authoritative source。`business state + Event + Outbox intent` 在同一 PostgreSQL transaction 内提交；Outbox Publisher 使用 `SKIP LOCKED` + durable lease 向现有 EventBus 做 at-least-once 发布。发布成功后、`published_at` 写回前崩溃可能导致重复通知，但不会重复业务副作用。

`READY_FOR_COMMIT` 只表示当前 payload 已审批并重新认证。Commit 仍会重新验证 Approval、Reauthentication、payload hash、Policy、payee、source account、balance 和 currency。`SUBMITTED` 不是成功；`UNKNOWN` 表示 Provider 可能已接收或执行，只能查询原 Operation，不得新建或换 key 重提。只有 `Operation SUCCEEDED` 才能展示“转账成功”。

`CREATED / SUBMITTED / UNKNOWN` 会按持久化 `next_reconcile_at` 自动恢复。多个 API process 可各自运行 worker；PostgreSQL `FOR UPDATE SKIP LOCKED` 与有期 lease 保证同一 Operation 在有效 lease 内只有一个 claim。Provider/network I/O 不持有数据库行锁。

Idempotency 和资金并发是两个独立 invariant：同一 idempotency key 通过 provider ledger unique constraint 仅执行一次；不同 Operation/key 通过 source-account-scoped PostgreSQL transaction advisory lock 不能并发花穿余额。Workflow balance check 仅用于 early validation，Provider commit-time balance check 才是最终资金 correctness boundary。

## 项目结构

```text
apps/api/                 FastAPI、LangGraph runtime、domain、persistence、tests
apps/web/                 Next.js Conversation 与 Reports UI
packages/api-client/      OpenAPI 生成的 TypeScript schema
scripts/                  Golden generation 与 smoke scripts
docs/                     版本交付、测试结果与设计记录
```

## 当前交付文档

- [Implementation Report v0.5.1](docs/implementation-report-v0.5.1.md)
- [Repository Tree v0.5.1](docs/repository-tree-v0.5.1.md)
- [Test Results v0.5.1](docs/test-results-v0.5.1.md)
- [Implementation Report v0.5.2](docs/implementation-report-v0.5.2.md)
- [Repository Tree v0.5.2](docs/repository-tree-v0.5.2.md)
- [Test Results v0.5.2](docs/test-results-v0.5.2.md)
- [Implementation Report v0.5.3](docs/implementation-report-v0.5.3.md)
- [Repository Tree v0.5.3](docs/repository-tree-v0.5.3.md)
- [Test Results v0.5.3](docs/test-results-v0.5.3.md)

旧版本文档继续保存在 `docs/` 作为审计和演进记录，但不是理解当前系统的必读入口。

## 当前限制

当前资金写入仅限持久化 Mock Transfer Provider；不支持真实转账 Provider、真实重新认证 Provider、FX、预约/周期转账、提交后取消、退款/冲正、raw transaction search、Planner、RAG、MCP 或 Agent-to-Agent 调用。

仍然没有 balance reservation/hold/capture 系统，也没有 durable generic task worker。Operation recovery 和 Outbox publisher 是两个明确、独立的专用 loop，不是 Celery、任务队列或通用调度框架。EventBus 仍是 process-local：多 API process 下，某个 publisher 的本地发布不保证另一 process 上的 SSE client 收到。本版也没有 client acknowledgement、SSE replay、Outbox archival/cleanup 或跨进程 realtime broker；Resource API 仍是事实源。
