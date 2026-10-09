# 历史档案：AI Banking Agent — FinancialAnalysisAgent & Routing v0.3.2

> 历史材料，保留原记录日期、版本和结论。旧风险规则、待办事项、测试数量与本地部署状态不代表 v0.10.3；当前说明见 [文档导航](../../README.md)。

Status: `IMPLEMENTED AND VERIFIED`

实施日期：2026-09-22。本轮实现 RequestRouter、轻量 AgentRegistry、FinancialAnalysisAgent、Task executor authoritative state 和 FinancialAnalysisSnapshot。没有实现 Skill、Report、Chart、raw transaction search 或写操作。`ManualAgentRuntime` 未修改。

## 1. Routing design

RequestRouter 使用现有 `LLMProvider` 进行一次轻量 JSON classification，并用 Pydantic `RouteDecision` 验证：

```text
MINIMAL_BANKING    -> agent:minimal-banking
FINANCIAL_ANALYSIS -> agent:financial-analysis
UNSUPPORTED        -> 直接生成当前能力说明，不启动 Agent
```

Router 最多重试一次。JSON 错误、未知 route、越界 confidence 或额外字段在两次后仍失败时，Task 以 `INTERNAL/ROUTING_FAILED` 失败。Router 不执行 Tool、不动态生成 Agent ID、不保存 prompt 或自由推理。

`request.routed` Event 只包含 `route` 和 `executor_id`。

## 2. AgentRegistry entries

AgentRegistry 仅注册：

- `agent:minimal-banking`
- `agent:financial-analysis`

每项是 typed `AgentDefinition(agent_id, instructions, allowed_capabilities)`，重复注册拒绝，没有 plugin framework 或 Agent-to-Agent 调用。

## 3. FinancialAnalysisAgent capability list

允许且仅允许：

```text
account.list
transaction.spending_summary
transaction.category_breakdown
transaction.compare_periods
transaction.top_transactions
```

`account.list` 允许 Minimal 和 Financial 两个 Agent；`account.get_balance` 仍只允许 Minimal Agent；四个 financial capabilities 仍只允许 Financial Agent。强制 `get_balance` 得到 `TOOL_NOT_ALLOWED`，强制 `execute_transfer` 得到 `TOOL_NOT_FOUND`。

Instructions 明确要求全部金融数字来自 Tool，禁止 LLM 加减乘除、合计、换算比例、四舍五入或改变精度。数字展示必须逐字符引用 Tool Result。

## 4. Income semantic correction

Income 修正为：

```text
POSTED + CREDIT + category != TRANSFER
```

Golden 2026-07 现为 `total_income=23800.00`、`income_transaction_count=1`。Spending、category、comparison、Top N 和 currency 规则不变。Fixture version 升为 `0.3.2`。

## 5. Task executor representation

Task type 从 `MINIMAL_AGENT_RUN` 泛化为 `BANKING_REQUEST`。Migration `0004` 新增 nullable authoritative fields：

```text
executor_type = AGENT
executor_id   = agent:minimal-banking | agent:financial-analysis
```

Router 完成后由服务器写入。`UNSUPPORTED` 没有 Agent executor，因此两字段保持 `null`。Frontend 通过 Task API 获取服务器状态，不自行推断。

Financial Agent 成功时 Task output 包含：

```text
agent_id
analysis_snapshot
assistant_message_id
steps
tool_calls
```

## 6. LangGraph agent-selection design

`LangGraphAgentRuntime` 只保留一套 Graph：

```text
AgentDefinition(request.agent)
    -> ContextBuilder(instructions + resolved tool schemas)
    -> shared LLM node <-> shared Tool node
```

Graph name 已泛化为 `banking-specialist-agent`，LangGraph runtime/context 中不再硬编码 Minimal Agent。Agent ID 进入 checkpoint state，成功 Tool Result 作为可序列化 evidence 保留。Manual runtime 仍使用旧的 constructor-bound Minimal Agent，代码未修改。

## 7. FinancialAnalysisSnapshot schema

Snapshot 由 Application 根据本次成功 Tool Results 确定性构造，不解析 LLM 文本：

```text
period: str | null
account_ids: list[str]
spending_summary: SpendingSummary | null
category_breakdown: CategoryBreakdown | null
period_comparison: SpendingPeriodComparison | null
top_transactions: TopTransactions | null
tool_evidence:
  - capability_id
  - sanitized input
```

Evidence 不保存 Chain-of-Thought、Router Prompt 或凭据。Top transactions 继续受 `1..20` 边界约束，不会把 138 条 raw history 放入 LLM context。

## 8. Golden grounding results

`test_financial_agent_grounding.py` 不使用另一个 LLM 打分，而是将 Agent 本次 Tool evidence/Snapshot 与 committed Golden 精确比较：

```text
2026-08 total_spending   = 16547.30
previous_spending        = 9333.20
absolute_change          = 7214.10
FOOD absolute_change     = 589.10
SHOPPING absolute_change = 2662.00
TRAVEL absolute_change   = 4260.00
```

Summary、category breakdown、period comparison 和 Top 5 整体 serialized structures 均与 Golden 全等。

## 9. Real DeepSeek routing traces

配置：`openai_compatible`，`api.deepseek.com`，`deepseek-v4-flash`，LangGraph + PostgreSQL checkpoint。API Key 未输出。

### Minimal route

```text
request: 我有哪些账户？
route: MINIMAL_BANKING
agent_id: agent:minimal-banking
tools: list_accounts({})
result summary: account_ids=[acc_salary, acc_savings, acc_credit, acc_travel]
final: 列出 4 个账户，未查询余额
```

### Financial analysis trace

```text
request: 帮我分析一下2026年8月份消费
route: FINANCIAL_ANALYSIS
agent_id: agent:financial-analysis
tools:
  get_spending_summary({month: 2026-08})
  get_category_breakdown({month: 2026-08})
  compare_spending_periods({month: 2026-08})
  get_top_transactions({month: 2026-08, limit: 10})
result summary:
  income=23800.00, spending=16547.30
  previous=9333.20, change=7214.10
  categories=9, top_items=10
final: 分开呈现事实与解释，share 保留 Tool 的 0..1 Decimal，未计算结余或消费/收入比
```

### Account-specific analysis trace

```text
request: 分析一下工资卡2026年8月的消费
route: FINANCIAL_ANALYSIS
agent_id: agent:financial-analysis
tools:
  list_accounts({}) -> acc_salary
  get_spending_summary({month: 2026-08, account_ids: [acc_salary]})
  get_category_breakdown({month: 2026-08, account_ids: [acc_salary]})
  get_top_transactions({month: 2026-08, account_ids: [acc_salary], limit: 5})
result summary:
  income=23800.00, spending=7657.30
  categories=5, top_items=5
final: 只解释 acc_salary，未把“工资卡”当作内部 ID
```

## 10. Security regression

- `分析8月消费，然后顺便给张三转1000` 被路由到 Financial Agent。
- Summary 可以成功读取；强制 `execute_transfer` 立即 `TOOL_NOT_FOUND`，Task FAILED，没有 write call。
- Financial Agent 强制 `get_balance` 为 `TOOL_NOT_ALLOWED`。
- Router 不能扩大 allowlist，未知 Agent/route 不会 fallback 到高权限 Agent。

## 11. Tests and results

- v0.3.1 preflight：`99 passed, 3 skipped`。
- v0.3.2 default suite：`131 passed, 3 skipped`。
- PostgreSQL integration：`3 passed, 131 deselected`。
- Ruff、uv lock check、Golden fixture validation：PASS。
- OpenAPI client generation：PASS，Task schema 包含 executor fields。
- Frontend lint/typecheck/build：PASS。
- Docker Compose API/Web build、migration `0004`、PostgreSQL health、API health：PASS。
- Real DeepSeek routing/financial/account-specific smoke：PASS。

## 12. Known limitations

- Router 是额外一次 LLM call，尚无 cache 或 deterministic fast path。
- Router structured output 通过严格 JSON prompt + Pydantic 实现；现有 Provider abstraction 还没有原生 response-format 参数。
- LLM 文本由 instructions 约束只引用 Tool 数字；服务器 authoritative grounding 边界是 Task 中的 structured Snapshot。本轮未增加自由文本数字 token 审计器。
- Unsupported route 是固定能力说明，不保存 Agent executor。
- 仍无 Skill、Report、Chart、raw search、anomaly detection 或真实 transaction persistence。

## 13. Deviations

- `FinancialAnalysisSnapshot.period` 允许 `null`，用于“未找到指定账户”且只成功调用 `account.list` 的如实回答；不会从自然语言中猜测 period。
- `UNSUPPORTED` 不是 Agent，所以 Task `executor_type/executor_id` 为 `null`，Task output 记录 route 和 assistant message ID。
- 真实 smoke 的 Top N 由模型选择为 10，仍在 schema 的 1..20 边界内。

## 14. Architecture questions

- 未来是否为 Router 增加 provider-native structured output，同时保留当前 Pydantic fail-closed 语义？
- 03.3 Report 显示层是否需要新增由 Python 生成的 formatted share/percentage 字段，避免 LLM 对长 Decimal 做任何格式化？
- 未来如果一个请求需要多 period 或多 account scope Snapshot，应扩展明确 schema，而不是让 LLM 合并证据。
