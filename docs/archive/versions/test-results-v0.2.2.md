# 历史档案：AI Banking Agent — 02.2 v0.2.2 Test Results

> 历史材料，保留原记录日期、版本和结论。旧风险规则、待办事项、测试数量与本地部署状态不代表 v0.10.3；当前说明见 [文档导航](../../README.md)。

执行日期：2026-09-20 至 2026-09-21（Asia/Shanghai）。

## Automated summary

| Gate | Result | Evidence |
|---|---|---|
| Ruff | PASS | `All checks passed!` for API source, tests and scripts |
| SQLite/Fake pytest | PASS | `57 passed, 3 skipped in 0.37s` |
| PostgreSQL integration | PASS | `3 passed, 57 deselected in 0.29s` |
| Dataset validation | PASS | accounts 4, transactions 138, payees 6, subscriptions 5 |
| Frontend lint | PASS | ESLint exit 0 |
| Frontend typecheck | PASS | `tsc --noEmit` exit 0 |
| Frontend build | PASS | Next.js production build; `/` 3.42 kB, First Load JS 105 kB |
| OpenAPI generation | PASS | `INTERRUPTED` and `RuntimeBackend` present |
| Docker Compose build/start | PASS | API/Web built; PostgreSQL healthy; API application startup complete |
| Real DeepSeek manual | PASS | four prompts completed safely |
| Real DeepSeek LangGraph | PASS | four prompts completed safely with PostgreSQL checkpoint |
| Browser E2E | PASS | LangGraph balance flow completed and survived refresh |

## Runtime parity matrix

| Scenario | Manual | LangGraph | Expected semantics |
|---|---|---|---|
| Direct final answer | PASS | PASS | step=1, tools=0 |
| `list_accounts → final` | PASS | PASS | tool order/count and Tool result context match |
| `list_accounts → get_balance → final` | PASS | PASS | steps=3, tools=2 |
| Invalid argument → model repair | PASS | PASS | recoverable structured Tool error |
| `TOOL_NOT_ALLOWED` | PASS | PASS | fatal; no second LLM request |
| `TOOL_OUTPUT_VALIDATION_FAILED` | PASS | PASS | fatal; no second LLM request |
| Provider failure | PASS | PASS | `EXTERNAL/LLM_PROVIDER_ERROR/retryable=true` |
| Step limit | PASS | PASS | `AGENT_STEP_LIMIT_EXCEEDED` |
| Tool-call limit | PASS | PASS | `AGENT_TOOL_CALL_LIMIT_EXCEEDED` |
| Forced `execute_transfer` | PASS | PASS | `TOOL_NOT_FOUND`, fatal, 0 writes |

## Hardening tests

- Tool dispositions：1 recoverable + 4 fatal mappings verified.
- Base URL：trailing slash normalized; relative/full endpoint/query configurations rejected.
- RuntimeFactory：unregistered backend fails closed.
- Reconciliation：PENDING/RUNNING → INTERRUPTED, COMPLETED unchanged, error/event verified.
- State security：no credential/database/client/session/policy/callable/reasoning fields.
- Developer Trace：runtime backend/checkpoint flag and sanitized metadata only.

## PostgreSQL checkpoint experiment

Test thread: `b092dedc-59e1-4e33-b0e1-080e55f5e87d`.

```text
Phase 1: list_accounts → tool complete → checkpoint persisted → interrupt
Destroy runtime and saver
Phase 2: new runtime/saver → same thread_id → checkpoint load
         → get_balance(acc_salary) → final

list_accounts count = 1
get_balance count = 1
```

Database assertion found rows in `checkpoints` for the Task thread. Saver-created tables were `checkpoint_migrations`, `checkpoints`, `checkpoint_blobs`, `checkpoint_writes`.

## Real Provider smoke

Sanitized configuration:

```text
provider=openai_compatible
base_url_domain=api.deepseek.com
model=deepseek-v4-flash
```

API Key was not printed.

### Manual

```text
我有哪些账户？
LLM → list_accounts → 4 accounts → final

我的工资卡余额是多少？
LLM → list_accounts → get_balance(acc_salary) → final
final = 23,864.52 CNY / ****6688
```

### LangGraph

```text
我有哪些账户？
LLM → list_accounts → 4 accounts → final

我的工资卡余额是多少？
LLM → list_accounts → get_balance(acc_salary) → final
final = 23,864.52 CNY / ****6688
```

### Security and hallucination

- Injection prompt: both real runtimes refused; 0 Tool calls, 0 writes.
- Forced FakeProvider `execute_transfer`: both runtimes failed immediately with `TOOL_NOT_FOUND`.
- Missing “黑金卡”: both real runtimes called `list_accounts`, reported no match, requested clarification, and invented no balance.

## Browser E2E

Docker Compose defaulted to `AGENT_RUNTIME=langgraph`. Conversation `f0e7eaeb-2138-49c4-bd6e-1181ff2db111`, Task `2aa17fa5-9625-4d3e-99f3-cc9d8f8425ef`:

```text
创建 Conversation
→ 发送“我的工资卡余额是多少？”
→ list_accounts
→ get_balance
→ Assistant Message
→ Task COMPLETED (version 7, steps 3, tool_calls 2)
→ browser refresh
→ Conversation / Messages / Task restored
```

## Commands

```bash
cd apps/api
.venv/bin/ruff check src tests ../../scripts
.venv/bin/pytest -q
.venv/bin/python ../../scripts/validate_mock_data.py

TEST_DATABASE_URL=postgresql+asyncpg://banking:banking@localhost:5432/banking_test \
  .venv/bin/pytest -m postgres -q

pnpm web:lint
pnpm web:typecheck
pnpm web:build
docker compose up -d --build
```

## Result

All executable 02.2 v0.2.2 acceptance categories passed. No Financial Analysis, new Banking Tool, Memory, RAG, MCP, Redis, Celery, Transfer Workflow, HITL or Multi-Agent capability was added.
