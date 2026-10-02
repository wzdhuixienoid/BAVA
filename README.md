# AI Banking Agent

当前版本：`v0.8.2`

面向中文用户的个人银行 Agent 应用。当前产品支持账户查询、消费分析、月度报告、安全转账、确定性异常交易提示、安全写熔断，以及订阅识别与取消。只有 `Operation SUCCEEDED` 才能表示转账或订阅取消已被对应 Mock Provider 最终确认。

核心设计原则：金融金额、分类汇总、占比、排名和环比全部由确定性 Python `Decimal` 代码计算；LLM 只负责意图识别、工具选择和基于可信事实的自然语言解释。

核心场景覆盖：

1. 智能转账        `COMPLETE`
2. 账单分析        `COMPLETE`
5. 订阅 / 代扣管理 `COMPLETE`

已达到赛题“至少 3 个核心场景”的要求。

## 当前能力

| 用户需求 | 执行者 | 能力 |
|---|---|---|
| 查看账户、查询余额 | `agent:minimal-banking` | `account.list`、`account.get_balance` |
| 月度支出、分类、环比、主要交易分析 | `agent:financial-analysis` | 四个只读 Financial Tools |
| 异常交易分析 | `agent:financial-analysis` | `transaction.detect_anomalies` → bounded deterministic Snapshot |
| 生成月度消费报告 | Financial Agent + `skill:monthly-spending-report` | Snapshot → immutable Report Artifact |
| 订阅分析 | `agent:subscription-analysis` | 自动识别周期扣费、按币种成本、涨价、即将续费 |
| 订阅管理分类 | deterministic Subscription service | `MANAGED` / `DETECTED_ONLY`，仅合同可管理者允许取消 |
| 安全取消订阅 | `workflow:subscription-cancel` | YELLOW → Approval → Operation → MockSubscriptionProvider |
| 动态风险分级 | deterministic Risk Policy | GREEN 查询自动执行；YELLOW 转账确认；RED 转账确认 + 强验证 |
| 转账全链路 | `workflow:transfer` | Draft → Validation → Risk → Approval → conditional Reauthentication → Operation |
| Operation 自动恢复 | PostgreSQL-backed recovery worker | due scan → `SKIP LOCKED` claim → lease → reconcile → retry/terminal |
| 并发转账资金安全 | `MockTransferProvider` | account-scoped advisory lock → authoritative balance → atomic ledger fact |
| 并发转账认证安全 | Application Risk Gate | user-scoped advisory lock → fresh daily exposure → controls → Operation |
| 安全熔断 | `SecurityGuardService` | 3 次连续强验证失败 / 10 min，或 5 次控制绕过 / 5 min → `WRITE_LOCKED` 15 min |
| 持久事件发布 | Transactional Outbox | Event + Outbox atomic commit → leased publisher → EventBus/SSE |
| 持久 Task 执行 | PostgreSQL-backed Task worker | due scan → `SKIP LOCKED` claim → lease/heartbeat/fencing → retry/terminal |
| 受约束复杂任务规划 | `ConstrainedPlanner` + `PlanValidator` | 只选已有高层 Capability，最多 8 步、一个写 Workflow |
| 持久化 Task DAG | `PlanExecutionService` + 现有 Task worker | attempt fencing、幂等恢复、用户等待、人工接管、只读回退 |
| 可信身份与多用户隔离（OIDC-ready） | provider-neutral OIDC/OAuth 2.0 | verified JWT → identity mapping → Principal → ownership/tool scope |

```text
Financial Analysis Vertical Slice: COMPLETE
Transfer Vertical Slice: COMPLETE
Subscription Management Vertical Slice: COMPLETE
Durable Operation Recovery: COMPLETE
Cross-Process Financial Concurrency: COMPLETE
Transactional Outbox: COMPLETE
Durable Task Execution: COMPLETE
可信身份与多用户隔离（OIDC-ready）：COMPLETE
动态风险分级：COMPLETE
异常交易识别：COMPLETE
安全熔断：COMPLETE
受约束复杂任务规划：COMPLETE
持久化 Task DAG：COMPLETE
受约束条件节点：COMPLETE
跨场景联动：COMPLETE
中断 / Human-in-the-loop：COMPLETE
有限安全回退：COMPLETE
人工接管：COMPLETE
```

### GREEN / YELLOW / RED

| 业务风险 | 确定性规则 | 用户控制 |
|---|---|---|
| GREEN（绿色） | 纯查询 / read-only financial tools | 自动执行，无 Approval，无 Reauthentication |
| YELLOW（黄色） | 可管理订阅取消 | Approval，无 Reauthentication |
| YELLOW（黄色） | 当日已成功 + 执行中 + 本笔 `<= 1000.00 CNY` | Approval |
| RED（红色） | 当日已成功 + 执行中 + 本笔 `> 1000.00 CNY` | Approval + Reauthentication |

Transfer 最低为 YELLOW。日累计按 `Principal.user_id` 和 `BANKING_BUSINESS_TIMEZONE` 的自然日计算，默认时区为 `Asia/Shanghai`。执行中 exposure 包含 `CREATED / SUBMITTED / UNKNOWN` Operation，排除 `FAILED`；Provider 已成功的同一笔 Operation 不会重复计算。

订阅查询为 GREEN；订阅取消固定为 YELLOW，必须 Approval，不需要 Reauthentication，也不会因订阅金额升级为 RED。

用户可以直接输入：

```text
我有哪些账户？
工资卡余额多少？
为什么2026年8月花这么多？
分析一下工资卡2026年8月的消费
生成一份2026年8月份消费报告
我有哪些订阅？最近有没有涨价的？
取消星幕视频
最近有没有异常交易？
```

报告生成后可在 Conversation 中通过 ReportCard 打开，也可以从 `/reports` 查看历史报告。

## 受约束任务规划

单个 Agent / Workflow 能完整完成的请求继续原路径，包括余额查询、消费分析、月度报告、独立转账和取消订阅。需要两个以上已有能力协作才进入 `COMPLEX_PLAN`。

```text
先查一下工资卡余额，再分析一下 2026 年 9 月的消费。
先看看我有哪些订阅，然后取消星幕视频。
查一下工资卡余额，如果余额不少于3000元，给张三转500元。
看看我的订阅，如果每月订阅费用不少于100元，取消星幕视频。
```

Planner 只选择 `ACCOUNT_QUERY / FINANCIAL_ANALYSIS / SUBSCRIPTION_ANALYSIS / TRANSFER_WORKFLOW / SUBSCRIPTION_CANCEL_WORKFLOW`。Proposal 不接受业务内部 ID、业务金额 payload、权限、风险或 Tool（条件 threshold 是 Decimal 字符串）；写 Workflow 始终从原始用户 Message 提取意图，沿用原有 Policy、Approval、Reauthentication、Security Guard、Operation 和 Provider。

v0.8.2 的数值条件只接受用户原始请求中明确给出的数值阈值；Planner 不能自行解释“够”“太多”“较高”等模糊表达为金额。确定性 grounding 仅匹配对应条件从句中的数值，转账等业务动作中的金额不能充当阈值。未给明确阈值时 fail closed，并提示用户提供明确金额；Planner 指定的币种也必须有原文依据，未写币种时沿用源结果的唯一币种规则。

`plans / plan_steps / plan_step_dependencies` 是固定持久化 DAG；`source_task_id` 唯一，Task retry 不再次规划。执行由原 Task worker 的 lease/attempt fence 保护，无独立 Plan worker。只读输出为 bounded structured facts；最终回答由服务器确定性整合这些事实，写步骤成功必须同时满足 Workflow 与 Operation `SUCCEEDED`。

`CONDITION` 是 Step kind，不属于 Agent Tool 或 Capability。只支持账户余额、本月支出、月度订阅成本三个预注册 `*_AT_LEAST` predicate；最多两个条件，每个能力步骤最多一个 TRUE guard。Validator 强制 source capability 匹配、source 属于依赖、guard 指向 CONDITION 且属于依赖，无条件嵌套。

`PlanConditionEvaluator` 只读取已完成 source 的 bounded output，使用现有 typed Snapshot 及 Decimal 比较。不同币种不换汇；省略币种仅允许唯一币种。Decision 保存实际值、阈值、币种、TRUE/FALSE、时间和 canonical JSON SHA-256。输入缺失/歧义或币种不合法会 FAILED，不伪装成 FALSE。

FALSE 在同一事务中将直接 guarded Step 标记 `SKIPPED / CONDITION_NOT_MET`，不创建 Workflow、Approval、Reauthentication、Operation 或 Provider 写入。其他步骤正常完成时 Plan / Task 仍 COMPLETED。TRUE 只允许进入原 Workflow，不构成 Approval、不预留余额、不保证最终资金可用；Workflow / Provider 在确认与 commit 时仍重新验证。

回退包含 CONDITION 的只读范围会清除 Decision，重新读取后计算新 hash。即使 FALSE 从未创建 Workflow，回退范围含写 Capability 仍拒绝。接管后 resume 读取已持久 Decision 和当前业务状态，不重新规划或重算已完成条件。

PlanCard 显示依赖和中文状态，关联业务继续使用原 Workflow Card。等待用户时 Step / Plan / Task 为 `WAITING_USER`；Operation 尚未收敛时为 `WAITING_EXTERNAL`。Workflow 状态事件在同一 transaction 中幂等重新调度原 Task。人工接管暂停编排并 fence 当前执行；业务卡片仍可操作，必须明确 resume 才能继续自动执行。

回退只重算目标及其下游的只读步骤，并清除旧输出、错误和时间戳；范围包含写 Capability 或 linked Workflow 时拒绝 `PLAN_ROLLBACK_NOT_SAFE`。回退不会撤销转账、恢复订阅或修改 Provider ledger。

## 架构

```text
User Message
  → Message + durable Task
  → RequestRouter
      ├─ simple request → existing Agent / Workflow
      └─ COMPLEX_PLAN → ConstrainedPlanner → PlanValidator
          → Persistent Plan DAG → TaskExecutionWorker / PlanExecutionService
              ├─ existing read-only Agent → bounded structured result
              │   → Deterministic CONDITION → TRUE → existing Workflow
              │                            → FALSE → guarded Step SKIPPED
              └─ existing Workflow → Policy → Approval → Reauthentication
                  → SecurityGuard → Operation → Provider
```


```text
OIDC Identity Provider
    → signed JWT access token → FastAPI authentication boundary
    → (issuer, subject) mapping → stable Principal.user_id
User Message
    → Message + durable Task + Event/Outbox atomic commit
    → PostgreSQL Task claim/lease + heartbeat
    → RequestRouter
    → AgentRegistry / deterministic Workflow
        ├─ MinimalBankingAgent
        ├─ FinancialAnalysisAgent → bounded TransactionAnomalySnapshot
        ├─ SubscriptionAnalysisAgent → bounded SubscriptionAnalysisSnapshot
        └─ SubscriptionCancellationWorkflow
    → LangGraphAgentRuntime
    → ToolRegistry → PolicyService → ToolExecutor
        ├─ transfer.commit (R4) / transfer.get_status (R1)
        └─ subscription.analyze (R1) / subscription.cancel (R4)
    → TransferRiskPolicy → persisted RiskDecision
        → user advisory lock → commit-time risk re-evaluation
    → SecurityGuardService → persistent NORMAL / WRITE_LOCKED state
    → Operation
        ├─ TRANSFER
        │  → MockTransferProvider
        │  → PostgreSQL account advisory lock
        │  → authoritative balance decision
        └─ SUBSCRIPTION_CANCEL
           → MockSubscriptionProvider
           → cancellation ledger
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
- Task 的调度、attempt、lease 和 fencing token 持久化在 Application PostgreSQL；LangGraph checkpoint 只保存 Agent runtime 进度，不代替 Task ownership。
- 外部 `(issuer, subject)` 只在认证边界映射到稳定的内部 `user_id`；Conversation、Task、Report、Workflow、Approval、Reauthentication、Operation 和银行数据均以该内部身份做 ownership scope。
- HTTP credential 不进入 Task、Message、Event、Outbox、Prompt 或 LangGraph checkpoint。Task worker 只从 Task 与 Conversation 的 authoritative `user_id` 构造 server-side execution Principal。
- 所有需实时通知的 durable Event 都与唯一 Outbox intent 在同一业务 transaction 内写入；Outbox 只引用 Event identity，不复制 payload。
- `security_guard_states` 保存当前 Principal 的熔断计数与期限；安全 signal 通过现有 Event + Outbox 留痕，不保存验证码、JWT 或隐藏推理。

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
- 异常规则固定为 `AMOUNT_SPIKE`、`RAPID_DUPLICATE`、`NEW_MERCHANT_HIGH_AMOUNT`、`SUBSCRIPTION_PRICE_SPIKE`；金额与比例只用 `Decimal`，baseline 按 Principal + currency 隔离。
- **异常提示 ≠ 已确认欺诈。**
- **异常交易检测结果不会自动触发 Security Write Lock。熔断由明确的安全执行失败信号触发。**
- Report exact Decimal 在 JSON 中序列化为 string；前端直接使用 Backend `*_display`，不重新计算或四舍五入。

> Financial Agents should receive deterministic summaries by default, not full transaction history.

## 权限边界

默认仍是只读和最小权限。静态 Tool 权限等级回答“谁可以调用该能力”；GREEN / YELLOW / RED 业务风险等级回答“当前这一笔请求需要哪些用户控制”。两者独立，业务风险不会扩大 Agent 的 Tool authority。

- 所有业务 API 都通过统一 `get_current_principal()` 认证；缺失/无效 credential 返回 401，未 provision 的合法外部身份返回 `403 IDENTITY_NOT_PROVISIONED`。
- detail、action 和 SSE 在查询层按 `Principal.user_id` 限定，跨用户 UUID 访问统一表现为 404；list 查询直接在 repository 层按用户过滤。
- LLM、Tool arguments、request body 和浏览器都不能提供或切换 authority。ToolExecutionContext 只能接收 server-created Principal，账户、收款人、余额和交易分析从该 Principal 获得 user scope。

- `agent:minimal-banking`：允许 `account.list`、`account.get_balance`。
- `agent:financial-analysis`：允许 `account.list`、四个 Financial Tools 和 `transaction.detect_anomalies`，不允许余额、转账、卡片或其他写能力。
- `agent:subscription-analysis`：只允许 `subscription.analyze`，不允许 `subscription.cancel`、Operation/Approval 写入。
- `skill:monthly-spending-report`：`allowed_tools=[]`，只能消费 `FinancialAnalysisSnapshot`。
- `workflow:transfer`：允许三项 R1 读能力，以及仅接受持久化 `operation_id` 的 `transfer.commit` (`R4_FINANCIAL_COMMIT`) 和 `transfer.get_status` (R1)。
- `workflow:subscription-cancel`：允许有界订阅读取、仅接受持久化 `operation_id` 的 `subscription.cancel` 和状态查询。
- Recovery worker 不是新的 Tool caller，也不扩大 `transfer.commit` allowlist；它只能 claim 已有 Operation，并调用与手工 reconcile 相同的 `OperationService` 状态转移。
- 任何 Agent 或 Skill 都看不到、也无权调用 `transfer.commit`；LLM 在意图提取后完全退出执行路径。
- Reports API 只有 GET list/detail，没有 POST、PUT、PATCH 或 DELETE。

Router 只选择 Agent/Workflow 和 requested output，不扩大权限。未知 Tool、越权调用和写操作请求均 fail closed。

## 快速启动

准备配置；认证模式必须显式指定，不存在缺省到 development principal 的 fallback：

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

本地开发可显式使用固定 Principal：

```env
APP_ENVIRONMENT=development
AUTH_MODE=development
DEVELOPMENT_USER_ID=dev-user-001
NEXT_PUBLIC_AUTH_MODE=development
```

OIDC 模式验证标准 JWT signature、`iss`、`aud`、`exp`、可选 `nbf`、`sub`、allowed algorithm 和 `kid`/JWKS。`OIDC_JWKS_URL` 留空时使用标准 discovery；生产环境禁止 `AUTH_MODE=development`。当前比赛能力为 OIDC-ready 的认证边界和多用户隔离，未接入真实生产 IdP。

```env
APP_ENVIRONMENT=production
AUTH_MODE=oidc
OIDC_ISSUER=https://idp.example.com
OIDC_AUDIENCE=banking-api
OIDC_JWKS_URL=
OIDC_ALLOWED_ALGORITHMS=["RS256"]
NEXT_PUBLIC_AUTH_MODE=oidc
NEXT_PUBLIC_OIDC_AUTHORITY=https://idp.example.com
NEXT_PUBLIC_OIDC_CLIENT_ID=banking-web
NEXT_PUBLIC_OIDC_SCOPE="openid profile"
```

转账日累计使用明确的业务时区：

```env
BANKING_BUSINESS_TIMEZONE=Asia/Shanghai
```

前端使用 Authorization Code + PKCE；access token 仅由成熟 OIDC client 保存在内存中并通过 Bearer header 发送，SSE 使用 authenticated fetch streaming，不把 token 放入 URL。外部身份必须显式 provision，系统不会按 email/display name 猜测或自动继承 demo 银行数据：

```bash
cd apps/api
uv run python -m banking_api.security.authentication.provision \
  --user-id dev-user-001 \
  --issuer https://idp.example.com \
  --subject external-subject
```

启动完整产品：

```bash
docker compose up --build
```

- Web：<http://localhost:3000>
- Reports：<http://localhost:3000/reports>
- API：<http://localhost:8000>
- OpenAPI：<http://localhost:8000/docs>

API 启动时依次执行 Alembic migration、LangGraph checkpoint setup、legacy stale Task 调度修复，然后启动 Task execution、Operation recovery 和 Outbox publication 三个专用 loop。关闭时三个 worker 都会停止并等待当前工作收敛。HTTP message handler 只持久化 Message/Task/Event/Outbox 并返回，不再拥有 Task 生命周期。

Task worker 通过环境变量配置：

```env
TASK_WORKER_ENABLED=true
TASK_WORKER_POLL_INTERVAL_SECONDS=0.5
TASK_WORKER_LEASE_SECONDS=60
TASK_WORKER_HEARTBEAT_SECONDS=15
TASK_WORKER_INITIAL_RETRY_SECONDS=2
TASK_WORKER_MAX_RETRY_SECONDS=120
TASK_WORKER_BACKOFF_MULTIPLIER=2
TASK_WORKER_BATCH_SIZE=4
TASK_WORKER_MAX_CONCURRENCY=4
```

`TASK_WORKER_HEARTBEAT_SECONDS` 必须小于 lease duration。batch 不超过本地 concurrency 上限，claim 后立即并发 dispatch，避免长 LLM Task 在队列尾部耗尽 lease。

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
GET  /api/v1/subscriptions
GET  /api/v1/subscriptions/{subscription_id}
GET  /api/v1/security/status
GET  /api/v1/plans?conversation_id=...
GET  /api/v1/plans/{plan_id}
POST /api/v1/plans/{plan_id}/actions/take-over
POST /api/v1/plans/{plan_id}/actions/resume
POST /api/v1/plans/{plan_id}/actions/rollback
GET  /api/v1/workflows/{workflow_id}
GET  /api/v1/workflows?conversation_id=...
POST /api/v1/workflows/{workflow_id}/actions/{set-recipient-query|select-payee|select-source-account|set-amount|select-subscription|approve|start-reauth|verify-reauth|commit|cancel}
GET  /api/v1/operations/{operation_id}
POST /api/v1/operations/{operation_id}/actions/reconcile
```

```text
/                    Conversation Workspace
/reports             Report history
/reports/{reportId}  Structured monthly report
/subscriptions       Subscription overview
```

SSE 用于实时通知；Task、Report 和 Workflow API 始终是页面刷新恢复的 authoritative source。`business state + Event + Outbox intent` 在同一 PostgreSQL transaction 内提交；Outbox Publisher 使用 `SKIP LOCKED` + durable lease 向现有 EventBus 做 at-least-once 发布。发布成功后、`published_at` 写回前崩溃可能导致重复通知，但不会重复业务副作用。

SSE connection 本身同样要求认证并先验证 Conversation ownership。OIDC 模式下浏览器通过 streaming `fetch` 在 `Authorization` header 携带 access token，不使用 query-string token。

`READY_FOR_COMMIT` 表示当前 payload 已审批并满足当前 RiskDecision 要求的控制；YELLOW 不需要 Reauthentication，RED 必须有效 Reauthentication。Commit 会在 Operation 创建前重新读取日 exposure 并评估风险。如 YELLOW 升级为 RED，保留 payload 未变的 Approval，不创建 Operation，转入 `REAUTH_REQUIRED`。风险在 payload 不变时不自动降级。

Commit 的 user risk advisory lock 只覆盖“重读 exposure → 风险评估 → 授权校验 → Operation 创建 → 事务提交”，不覆盖 Provider I/O。它保护用户级日认证门槛；Mock Provider 的 account lock 保护账户余额，两者彼此独立。`SUBMITTED` 不是成功；`UNKNOWN` 只能查询原 Operation，不得新建或换 key 重提。只有 `Operation SUCCEEDED` 才能展示“转账成功”。

`CREATED / SUBMITTED / UNKNOWN` 会按持久化 `next_reconcile_at` 自动恢复。多个 API process 可各自运行 worker；PostgreSQL `FOR UPDATE SKIP LOCKED` 与有期 lease 保证同一 Operation 在有效 lease 内只有一个 claim。Provider/network I/O 不持有数据库行锁。

Task 执行同样使用 PostgreSQL `FOR UPDATE SKIP LOCKED`、持久 lease、attempt fencing 和 heartbeat。保证是“at-least-once execution attempt + fenced authoritative completion”，不是外部副作用 exactly-once。Report 依赖 `source_task_id` 唯一约束；Plan retry 复用同一 DAG，写步骤 retry 通过 source_task_id 找回同一 Workflow（包括 Workflow 已创建但尚未保存 link 的 crash window）。Transfer retry 复用同一 Workflow，金融副作用仍只由 Operation/Provider/OperationRecoveryWorker 收敛。

Idempotency 和资金并发是两个独立 invariant：同一 idempotency key 通过 provider ledger unique constraint 仅执行一次；不同 Operation/key 通过 source-account-scoped PostgreSQL transaction advisory lock 不能并发花穿余额。Workflow balance check 仅用于 early validation，Provider commit-time balance check 才是最终资金 correctness boundary。

`WRITE_LOCKED` 只阻止新的 Transfer / Subscription cancel Operation 以及 reauthentication start/verify；GREEN 查询、异常分析和状态查询继续可用。Operation 创建前服务端 fail closed，因 lock 拒绝时不消费 Approval、不创建 Operation、不调用 Provider。`locked_until` 到期后 lazy clear，无后台 unlock worker。

已有 Operation 的 commit retry 在取得 Security Guard user lock 后先返回原记录，即使客户端使用创建前版本且用户随后 WRITE_LOCKED，也不重消费 Approval 或换 idempotency key。CREATED / SUBMITTED / UNKNOWN 继续由原 Recovery 收敛，不重新检查用户写锁。

Security Guard 状态转移与新 Operation 创建共享同一个 Principal-scoped PostgreSQL transaction advisory lock。Authoritative write gate 与 Operation/Approval/Workflow 更新在同一 transaction 中，因此 lock activation 与 Operation creation 对同一用户有唯一线性化顺序。Transfer 的全局锁顺序固定为 `Security Guard user lock → Transfer Risk user lock`；Subscription cancellation 只获取前者。

## 项目结构

```text
apps/api/                 FastAPI、LangGraph runtime、domain、persistence、tests
apps/web/                 Next.js Conversation 与 Reports UI
packages/api-client/      OpenAPI 生成的 TypeScript schema
scripts/                  Golden generation 与 smoke scripts
docs/                     版本交付、测试结果与设计记录
```

## 当前交付文档

- [Implementation Report v0.8.2](docs/implementation-report-v0.8.2.md)
- [Repository Tree v0.8.2](docs/repository-tree-v0.8.2.md)
- [Test Results v0.8.2](docs/test-results-v0.8.2.md)
- [Implementation Report v0.8.1](docs/implementation-report-v0.8.1.md)
- [Repository Tree v0.8.1](docs/repository-tree-v0.8.1.md)
- [Test Results v0.8.1](docs/test-results-v0.8.1.md)

## 当前限制

Plan 最多 8 步、2 个 CONDITION、一个写 Workflow，按 ordinal 顺序执行 ready steps；条件只有预注册 Predicate，不支持 ELSE、nested conditions、任意表达式、AND/OR、loops、多写 Workflow、动态重规划或自由 Agent 协商。复杂请求中的月度 Report Artifact 暂未作为 Plan Capability 注册，会整体拒绝；独立分析并生成报告仍走完整 Financial vertical slice。没有 Plan cancel API，业务取消沿用 Workflow。


当前写入仅限比赛 synthetic banking environment 中的持久化 `MockTransferProvider` 和正式 `MockSubscriptionProvider`；未连接真实商户订阅 API。RED 强验证使用 `MockReauthenticationProvider`。

订阅检测当前只支持固定的月度/年度 cadence 窗口和 fixture alias；不做 FX、不根据商户类型主观判断“重复”，不推断用户是否真正使用某项订阅，也未实现主动通知调度。

异常检测只是可解释的确定性分析，不是完整 Fraud Detection Platform；不做 FX、主动通知、Fraud ML、通用 Rule Engine/DSL 或人工审核台。Security Guard 只有 `NORMAL / WRITE_LOCKED`，本版无管理员手工解锁。

登录 Authentication 只回答“是谁”，不替代 canonical payload Approval，也不替代 RED 在 commit 前要求的 Reauthentication。

仍然没有 balance reservation/hold/capture 系统。TaskExecutionWorker、OperationRecoveryWorker 和 OutboxPublisher 是三个明确、独立的专用 loop，不是 Celery、Redis、Kafka、通用任务队列或 Generic Worker/Scheduler Framework。Task worker 仍由 API process 托管，未提供独立 worker deployment、优先级队列或 per-conversation ordering。

EventBus 仍是 process-local：多 API process 下，某个 publisher 的本地发布不保证另一 process 上的 SSE client 收到。本版也没有 client acknowledgement、SSE replay、Outbox DLQ、archival/cleanup、分布式 metrics/tracing 或跨进程 realtime broker；Resource API 仍是事实源。

真实 HTTP + 当前 LLM 的 Plan smoke 使用独立 synthetic 数据库和最新 API：

```bash
PLAN_SMOKE_BASE_URL=http://127.0.0.1:8001 \
  uv run --project apps/api python scripts/smoke_plan_product.py
```

该脚本完成只读 DAG，以及一次明确 Approval + commit 的 synthetic 订阅取消，并核对原 Operation 幂等复用；不要指向真实业务环境。
