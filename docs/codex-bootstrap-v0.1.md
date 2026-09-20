# AI Banking Agent — Codex Bootstrap 规格 v0.1

状态：`FROZEN FOR BOOTSTRAP`  
架构基线：`v0.1`  
Bootstrap 迭代：`Iteration 0`

本文档记录构建当前代码库时使用的 Iteration 0 规范。它只定义应用骨架；下一阶段的 Minimal Agent Runtime 不在本轮范围内。

## 目标与必需链路

建立一个结构正确、可持久化、可测试的模块化单体，并证明以下链路能够运行：

```text
Browser → Next.js → POST Message → FastAPI → 持久化 Conversation/Message
        → Task → 确定性 Bootstrap Runtime → 持久化状态变化
        → 持久化 Event → SSE → Frontend 刷新 → Task UI 更新
```

本轮不包含任何真实 LLM 推理。

## 产品语言

产品面向中国用户，用户可见 UI、系统回复和错误提示以中文为主。API 字段、Event type、Task type 与状态枚举保持稳定的英文机器标识，由 Frontend 映射为中文显示文案。

## 冻结的架构约束

1. Workflow First, Agent Second。不得创建 Transfer、Card、Subscription、Wealth 或 Lifestyle Agent。
2. Frontend 只调用 Banking Application API，不直接调用 Agent Framework。
3. Domain Model 不依赖 Agent Framework。
4. 结构化持久状态是业务事实来源，不能只依赖 `messages[]`。
5. Task、Workflow、Approval、Operation 的结果以 Server State 为准。
6. Default Deny。本轮不注册任何高风险写能力。
7. Backend 使用模块化单体；Mock Bank、Policy 和 Runtime 不拆成微服务。
8. 优先使用显式实现，不创建 Generic Repository、通用 Factory 或万能 Context/State。

## 技术基线

- Monorepo：Next.js、React、TypeScript、Tailwind CSS
- Python 3.12+、FastAPI、Pydantic、Pydantic Settings、SQLAlchemy 2.x、asyncpg、Alembic
- PostgreSQL；不使用 Redis
- FastAPI `StreamingResponse` SSE 与进程内实时 EventBus
- uv、pytest、pytest-asyncio、ruff、pnpm、ESLint、TypeScript、openapi-typescript

禁止引入的运行依赖包括：LangGraph、LangChain、AutoGen、AgentScope、MCP SDK、Vector Database、Embedding/RAG Framework、Redis、Kafka、RabbitMQ、Celery、Kubernetes、真实银行/认证 Provider，以及所有 LLM SDK。

## 持久化 Domain Model

Iteration 0 只包含以下应用表：

- `conversations`：id、user_id、title、created_at、updated_at
- `messages`：id、conversation_id、role、content、created_at
- `tasks`：id、conversation_id、task_type、status、input_json、output_json、error_json、version、created_at、updated_at
- `events`：id、event_type、conversation_id、task_id、全局 sequence、data_json、created_at

Message role 只允许 `USER`、`ASSISTANT` 和 `SYSTEM_NOTICE`，不允许 Agent-specific role。

Task status 包含 `PENDING`、`RUNNING`、`WAITING_USER`、`WAITING_EXTERNAL`、`COMPLETED`、`FAILED`、`CANCELLED` 和 `SKIPPED`。Bootstrap Runtime 只使用 `PENDING`、`RUNNING`、`COMPLETED` 和 `FAILED`。每次 Task 状态变化必须增加 `version`。

Event sequence 全局稳定递增。Event 必须持久化，SSE 永远不是持久化事实来源。

## 只定义 Schema 的边界

Workflow、Approval 和 Operation 只冻结未来概念，不创建数据库表、API 或执行逻辑。

- Workflow：id、type、status、version
- Approval：id、workflow id、payload hash、status 和时间戳；状态包括 `PENDING`、`APPROVED`、`REJECTED`、`EXPIRED`、`CONSUMED`、`INVALIDATED`
- Operation：id、workflow id、idempotency key、status、external reference；状态包括 `CREATED`、`SUBMITTED`、`UNKNOWN`、`SUCCEEDED`、`FAILED`

Workflow 是具有显式状态变化的确定性业务流程。未来高风险金融操作必须通过 Workflow 执行，不能由 Agent 直接执行。

## 确定性 Bootstrap Runtime

收到一条 User Message 后：

1. 持久化 User Message。
2. 创建 `BOOTSTRAP_MESSAGE_PROCESSING` Task，初始状态为 `PENDING`。
3. 持久化并发布 `task.created`。
4. 将 Task 转换为 `RUNNING`，持久化并发布 `task.started`。
5. 只执行确定性处理。
6. 持久化 Assistant Message：`启动运行时已收到你的消息。`
7. 将 Task 转换为 `COMPLETED`，持久化并发布 `task.completed`。
8. 持久化并发布 Assistant Message Event。
9. 受控异常必须将 Task 转换为 `FAILED`，并产生 `task.failed`。

允许用极短 delay 帮助观察 UI 状态，但 delay 不是业务逻辑依赖。该 Runtime 必须容易删除，不得演化为未来 Agent 架构的基础。

## Registry、安全与上下文边界

- AgentRegistry、SkillRegistry、WorkflowRegistry、ToolRegistry 使用简单的 typed dictionary registration，并且初始为空。
- Tool metadata 预留 capability id、name、risk、side effect、allowed callers。本轮不注册高风险写能力。
- Policy decision 包含 `ALLOW`、`DENY` 和 Approval/Re-auth 组合。未知能力默认 `DENY`。
- ContextEnvelope 预留 Task、Conversation、Memory、Upstream Results 和 Constraints；不实现 Retrieval、RAG、Prompt Construction 或 Token Budgeting。
- MockBankService 只提供确定性的 `list_accounts()` 和 `get_account_summary()`。它不是正式 Tool，不得包含写方法。

## Persistence 与 Repository 规则

API Route 不直接执行 SQL。Conversation、Message、Task 和 Event 分别使用显式 Repository；不得建立 Generic Repository 或复杂 Unit of Work Framework。生产数据库为 PostgreSQL，Schema 由 Alembic 管理。

## HTTP API

- `GET /health` → `{"status":"ok"}`
- `GET/POST /api/v1/conversations`
- `GET /api/v1/conversations/{conversation_id}`，响应包含 Messages
- `POST /api/v1/conversations/{conversation_id}/messages` → 202，并返回 message_id、task_id、request_id
- `GET /api/v1/tasks?conversation_id=...`
- `GET /api/v1/tasks/{task_id}`
- `GET /api/v1/events?conversation_id=...`，响应为 SSE

不得创建 Transfer、Purchase、Card Write、Cancellation、`/agents`、`/skills` 或 Framework-specific Endpoint。`DevPrincipal` Dependency 提供 `dev-user-001`，Route 不直接硬编码身份。

## Event Protocol 与 SSE

统一 Event Envelope 包含 event_id、event_type、timestamp、conversation_id、可为空的 task_id、sequence 和 data。本轮支持：

- `conversation.message.created`
- `conversation.message.completed`
- `task.created`
- `task.started`
- `task.completed`
- `task.failed`

Event 名称描述 Domain/Runtime 状态，不描述内部 Agent。进程内 EventBus 明确属于单进程 Bootstrap 基础设施。SSE 断开后，客户端通过 GET API 恢复 Conversation 和 Task；Event replay 与分布式 fan-out 延后实现。

## Frontend 契约

Workspace 支持创建和加载 Conversation、发送 Message、显示 User/Assistant Message，以及展示 Task type、status、id。Frontend 为当前 Conversation 建立 `EventSource`。收到相关 Event 后，必须重新获取权威的 Conversation 和 Task 数据。只有当前选择、输入框、连接状态和 UI 展示状态可以保存在本地。

Pydantic/OpenAPI 是 API 类型来源。`pnpm api:generate` 从运行中的 FastAPI `/openapi.json` 生成 `packages/api-client/src/schema.d.ts`。

## Compose 与环境变量

Docker Compose 只包含 PostgreSQL、API 和 Web。`.env.example` 声明 PostgreSQL、Database URL、API host/port、Web port 和公开 API base URL。完整应用的目标启动命令是：

```bash
docker compose up --build
```

## 必需验证

- Health 返回 200
- Conversation 和 Message 能够持久化
- Message 能够创建 Task
- Runtime 最终产生持久化 `COMPLETED`，并支持持久化 `FAILED`
- 状态变化产生有序、持久化的 Event
- 实时 EventBus 能够投递已经持久化的 Event
- Backend tests 和 ruff 通过
- Frontend lint、typecheck 和 production build 通过
- OpenAPI TypeScript 生成成功
- 依赖审计不存在 LLM、Agent Framework、MCP、RAG/Vector、Redis 或高风险银行执行能力

## 当前限制

Iteration 0 不包含 LLM、Agent、真实 Skill、具体 Workflow、Approval Execution、Operation Execution、Re-authentication、Memory、RAG、Scheduler、Worker、分布式 Event Transport、真实银行 API 或真实认证。Bootstrap 完成后必须停止，未经新规格不得进入下一阶段。

## 架构问题

本轮实现未发现需要改变冻结架构的 Architecture Question。
