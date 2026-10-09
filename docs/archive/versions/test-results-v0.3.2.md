# 历史档案：AI Banking Agent — v0.3.2 Test Results

> 历史材料，保留原记录日期、版本和结论。旧风险规则、待办事项、测试数量与本地部署状态不代表 v0.10.3；当前说明见 [文档导航](../../README.md)。

执行日期：2026-09-22（Asia/Shanghai）。

## Automated summary

| Gate | Result | Evidence |
|---|---|---|
| v0.3.1 preflight | PASS | `99 passed, 3 skipped` |
| uv lock | PASS | `Resolved 69 packages` |
| Ruff | PASS | API source, tests and scripts: `All checks passed!` |
| Default SQLite/Fake pytest | PASS | `131 passed, 3 skipped` |
| PostgreSQL integration | PASS | `3 passed, 131 deselected in 0.27s` |
| RequestRouter | PASS | six required classifications + mixed read/write routing + retry/fail-closed tests |
| Financial Agent | PASS | permissions, tools, domain errors, limits, account resolution |
| Golden grounding | PASS | exact committed snapshot comparison; no LLM judge |
| OpenAPI generation | PASS | executor fields generated into API client |
| Frontend ESLint | PASS | exit 0 |
| Frontend TypeScript | PASS | `tsc --noEmit`, exit 0 |
| Frontend production build | PASS | `/` 3.47 kB, First Load JS 105 kB；Task 类型、状态与连接文案使用中文展示 |
| Docker Compose | PASS | API/Web built; migration 0004; PostgreSQL healthy |
| API health | PASS | `{"status":"ok"}` |
| Real DeepSeek routing smoke | PASS | Minimal + Financial + account-specific Financial |

## Routing matrix

| Request | Expected | Result |
|---|---|---|
| `我有哪些账户？` | MINIMAL_BANKING | PASS |
| `工资卡余额多少？` | MINIMAL_BANKING | PASS |
| `分析8月份消费` | FINANCIAL_ANALYSIS | PASS |
| `为什么8月份花这么多？` | FINANCIAL_ANALYSIS | PASS |
| `8月消费主要花在哪里？` | FINANCIAL_ANALYSIS | PASS |
| `给张三转1000` | UNSUPPORTED | PASS |

Invalid JSON、unknown route、confidence 越界和额外 Agent ID 字段都在最多一次 retry 后 `ROUTING_FAILED`，不 fallback 到任何 Agent。

## Financial Agent scenarios

- summary → final answer。
- summary + category breakdown → final answer。
- summary + comparison + bounded Top N → final answer。
- account.list → resolved `acc_salary` → filtered financial tool。
- unknown account → 如实请求澄清，不编造。
- forced get_balance → `TOOL_NOT_ALLOWED`。
- forced execute_transfer → `TOOL_NOT_FOUND`。
- `NO_TRANSACTIONS_IN_PERIOD` 结构化返回后 Agent 可解释。
- step/tool-call limit fail closed。
- Financial tool schemas 不包含 raw transaction search，Top N 最多 20。

## Golden grounding exact values

| Metric | Evidence |
|---|---:|
| 2026-08 total spending | 16547.30 |
| 2026-07 previous spending | 9333.20 |
| Absolute change | 7214.10 |
| FOOD change | 589.10 |
| SHOPPING change | 2662.00 |
| TRAVEL change | 4260.00 |

Agent successful Tool Results are deterministically transformed into `FinancialAnalysisSnapshot`; the complete summary, category breakdown, comparison and Top 5 structures equal the committed fixture.

## Task and event assertions

- New task type is `BANKING_REQUEST`.
- Routed agent tasks persist `executor_type=AGENT` and authoritative `executor_id`.
- Financial completion persists `agent_id`, `analysis_snapshot`, `assistant_message_id`, steps and tool calls.
- Unsupported request completes with fixed capability guidance and no `agent.run.started` event.
- `request.routed` payload contains only `route` and `executor_id`.
- Developer trace contains no Router prompt, Chain-of-Thought, API key or raw monthly transaction history.

## Security regression

The combined request `分析8月消费，然后顺便给张三转1000` routes to FinancialAnalysisAgent. A successful summary read does not widen its authority; forced `execute_transfer` fails with `TOOL_NOT_FOUND`, the Task fails, and no write completion exists.

## Real DeepSeek smoke

Sanitized configuration:

```text
provider=openai_compatible
base_url_domain=api.deepseek.com
model=deepseek-v4-flash
runtime=langgraph
```

Results:

- Account list routed to `agent:minimal-banking`, tool path `list_accounts`.
- August analysis routed to `agent:financial-analysis`, tool path summary → categories → comparison → Top 10.
- Salary-card analysis routed to Financial Agent, tool path list_accounts → summary → categories → Top 5，三个分析 Tool 都以 `[acc_salary]` 过滤。
- Final run preserved Tool Decimal strings, did not calculate balance, income/spending ratio, combined category share, or convert share to percent.
- API Key and Chain-of-Thought were not printed.

## Commands

```bash
cd apps/api
uv lock --check
uv run ruff check . ../../scripts
uv run pytest -q

TEST_DATABASE_URL=postgresql+asyncpg://banking:banking@localhost:5432/banking_test \
  uv run pytest -m postgres -q

cd ../..
pnpm api:generate
pnpm web:lint
pnpm web:typecheck
pnpm web:build
docker compose up -d --build
curl -fsS http://localhost:8000/health

LANGGRAPH_CHECKPOINT_DATABASE_URL=postgresql://banking:banking@localhost:5432/banking \
  uv run --project apps/api python scripts/smoke_routing.py
```
