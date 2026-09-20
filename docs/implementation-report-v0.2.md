# AI Banking Agent — 02.1 v0.2 Implementation Report

Status: `PRE-REAL-LLM IMPLEMENTATION COMPLETE`  
Date: `2026-09-20`

本报告对应用户授权的范围：完成真实 LLM smoke test 之前的实现。真实 DeepSeek、prompt-injection/hallucination real smoke 和其后的 Browser E2E 尚未执行，因此当前不声称真实 LLM integration 已验证。

## 1. Files created / modified

主要新增：

- `banking_api/llm/`：内部模型、Protocol、Fake Provider、OpenAI-compatible adapter
- `banking_api/agents/minimal_banking_agent.py`
- `banking_api/tools/`：Pydantic schema、两个 banking tools、executor
- `banking_api/runtime/agent_runtime.py`、`task_runner.py`
- `banking_api/mock_bank/data/*.json`
- migration `0002_agent_task_progress.py`
- dataset generator/validator、real smoke script
- Fake runtime、provider、dataset、SQLite E2E、PostgreSQL integration tests
- Frontend `TaskProgress` 与重新生成的 OpenAPI TypeScript schema

主要修改：Settings、ContextBuilder、ToolRegistry、PolicyService、MockBankService、Message API、Task/Event API、Task persistence、App composition、SSE event list、Docker/Makefile/README。旧 `BootstrapRuntime` 已移除。工作区原有的 `AI Banking Agent v0.1` 删除状态属于用户既有变更，本轮未操作。

## 2. Synthetic Dataset summary

- accounts: 4
- transactions: 138（2026-06-03 至 2026-09-20，deterministic seed `20260920`）
- payees: 6（包含两个“张三”）
- subscriptions: 5

数据包含固定工资/房租、餐饮、通勤、水电通信、八月额外外卖与旅行、订阅、大额购物、健康和账户间转账。数据文件不保存完整卡号，全部为虚构掩码值。

## 3. LLMProvider design

`LLMProvider` 只暴露 `async generate(LLMRequest) -> LLMResponse`。Runtime 只依赖 `LLMRequest`、`LLMResponse`、`LLMMessage`、`LLMToolCall`、`LLMToolDefinition`、`LLMUsage`，不接触 provider-native response。

`FakeLLMProvider` 接收脚本化的 response/exception 队列，并记录 deep-copied request，支持直接回答、单/多步 Tool、非法参数、未知 Tool、Provider failure 与无限 loop 测试。

## 4. OpenAICompatibleProvider implementation

使用轻量 `httpx` 调用 `{LLM_BASE_URL}/chat/completions`，在 adapter 内完成内部模型和 OpenAI-compatible JSON 的双向映射。`base_url`、API Key、model、timeout 全由 Settings 注入；其他模块不知道具体厂商。HTTP、协议和 response mapping failure 统一转换为 `LLMProviderError`。

## 5. Actual provider configuration used for smoke test

- provider type: `openai_compatible`（实现与 adapter 单元测试已验证）
- base URL domain: `NOT CONFIGURED`
- model: `NOT CONFIGURED`
- API Key: 未提供、未输出

真实 smoke 未执行，等待用户后续填写 `.env`。

## 6. Manual Agent Loop algorithm

Runner 以独立 session 将 Task 转为 RUNNING并加载最近消息；Runtime 构建 context、调用 LLM、识别 final/tool calls、逐个执行 Tool、把结构化 Tool Result 追加到仅驻留内存的 runtime context，再次调用 LLM。Final answer 由 Runner 持久化为 Assistant Message，并完成 Task。

Runtime state 包含 `task_id`、`conversation_id`、`step_count`、`tool_call_count`、`runtime_messages`、`status`，与 Domain Task 分离。

## 7. ToolRegistry contents

仅有：

1. `account.list` → `list_accounts`
2. `account.get_balance` → `get_balance`

两者 `risk_level=R1_PRIVATE_READ`、`side_effect=false`、`allowed_callers={agent:minimal-banking}`。Transaction/Payee/Subscription/Transfer 没有注册。

## 8. Authorization path

每次调用严格执行 `ToolRegistry lookup → PolicyService evaluate → ToolExecutor schema validation/execution/output validation → MockBankService`。唯一 ALLOW 条件为 authenticated、caller 匹配、显式注册、R1 私有读取、无副作用且在 agent allowlist；其他全部 DENY。Unknown Tool 在 registry lookup 阶段 fail closed，未知 caller 在 Policy 阶段 fail closed。

## 9. ContextBuilder contents

只包含：MinimalBankingAgent instructions、当前任务（最新 User Message）、最近 10 条 USER/ASSISTANT 消息、两个 allowed Tool input schemas，以及本次 run 的 assistant tool-call/tool result messages。不包含 Memory、RAG、summary、SYSTEM_NOTICE、内部 Event、credential 或 Chain-of-Thought。

## 10. Runtime events

保留产品事件并增加 `task.progress`、`agent.run.started/completed/failed`、`llm.request.started/completed`、`tool.call.started/completed/failed`。Developer trace endpoint 只返回授权用户所属 Task 的持久化 sanitized metadata：step、计数、tool name、argument keys、output keys/error code、usage；不保存 Prompt dump、参数值、余额或完整 Tool Result。

## 11. Error handling

已实现 `TOOL_NOT_FOUND`、`TOOL_NOT_ALLOWED`、`TOOL_ARGUMENT_VALIDATION_FAILED`、`TOOL_OUTPUT_VALIDATION_FAILED`、`TOOL_EXECUTION_FAILED`。错误以结构化 Tool Result 返回 LLM，允许在剩余预算内修正。Provider failure 映射为 `category=EXTERNAL`、`code=LLM_PROVIDER_ERROR`、`retryable=true`，默认无自动 retry。

## 12. Loop limits

Settings 默认 `AGENT_MAX_STEPS=6`、`AGENT_MAX_TOOL_CALLS=4`。Runtime 在边界处产生 `AGENT_STEP_LIMIT_EXCEEDED` 或 `AGENT_TOOL_CALL_LIMIT_EXCEEDED`，Runner 将 Task 置为 FAILED。

## 13. FakeLLM automated test results

SQLite/default suite：`24 passed, 1 skipped`。覆盖直接回答、list→final、list→balance→final、unknown tool、unauthorized/unauthenticated caller、invalid arguments、tool/output failure、provider failure、max step、max tool-call、ContextBuilder、Provider mapping、dataset 和持久化 Runtime E2E。

Ruff：PASS。

## 14. PostgreSQL integration test results

使用独立 `banking_test` 数据库：`1 passed, 24 deselected`。验证 Alembic 到 `0002`、Conversation/Message/MINIMAL_AGENT_RUN 持久化、Task version、Event sequence、JSON fields 和三步 Fake Agent Runtime E2E。未连接生产数据库。

## 15. Real LLM smoke traces

`NOT RUN` — 用户尚未提供 `LLM_BASE_URL / LLM_API_KEY / LLM_MODEL`。`scripts/smoke_agent.py` 已准备，默认测试不会触发网络。

## 16. Prompt-injection smoke result

Real smoke：`NOT RUN`。Fake automated safety case已验证 `execute_transfer` 返回 `TOOL_NOT_FOUND`，Registry 中不存在任何写 Tool，Agent 无法扩大 allowlist。

## 17. Hallucination smoke result

Real smoke：`NOT RUN`。Synthetic Dataset 中不存在“黑金卡”；真实模型行为须在配置后验证。Runtime/Tool 层不会返回该账户或余额。

## 18. Browser E2E result

按规格顺序位于 Real LLM smoke 之后，本轮未执行交互式 Browser E2E。已完成 Frontend lint、TypeScript typecheck、production build；Compose 启动后 API health 返回 `{"status":"ok"}`，Web HTTP 返回 `200`。

## 19. Dependency changes

`httpx` 从 dev dependency 移至 runtime dependency，仅 OpenAI-compatible adapter 直接使用。未加入 LangGraph、LangChain、Agents SDK、MCP SDK、RAG、Vector DB、Redis 或 Celery。`uv.lock` 已通过 `uv lock --check`。

## 20. Known limitations

- 尚未用 DeepSeek 完成真实 function-calling 验证。
- In-process Task 在进程崩溃后不会自动恢复。
- 固定开发身份，不是生产 Authentication。
- 单进程 EventBus；无分布式 realtime transport。
- SSE 无 Last-Event-ID replay。
- Provider base URL 语义为 API root，adapter 固定追加 `/chat/completions`。
- Tool error 默认回馈模型而不是立即终止 Task；最终仍受预算限制。

## 21. Deviations from specification

- `ToolSpec.input_schema/output_schema` 作为 Pydantic model 派生 property，而非另存一份可能漂移的 dict。
- 为让刷新后的前端也能展示进度，增加 `tasks.progress_message` 和 migration `0002`。
- 未使用厂商 SDK，选择已有的轻量 `httpx`，Provider 差异仍完全限制在 adapter。
- 真实 LLM smoke、其安全/幻觉场景以及之后的 Browser E2E 按用户本轮范围明确延期。

## 22. Architecture questions

1. 下一轮是否要求进程重启时扫描并恢复 RUNNING/PENDING Task，还是继续接受 in-process best-effort？
2. Tool validation/execution failure 当前回馈模型修正；是否有某些错误类别应立即 fail Task？
3. `LLM_BASE_URL` 是否统一定义为 API root（当前固定追加 `/chat/completions`），以避免兼容服务传入完整 endpoint 时产生歧义？
4. 未来认证接入后，authenticated/user ownership 是否由不可伪造的 Principal 快照写入 Task，供异步 Runner 重新鉴权？
