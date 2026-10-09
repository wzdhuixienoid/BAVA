# 历史档案：AI Banking Agent — v0.3.4 Test Results

> 历史材料，保留原记录日期、版本和结论。旧风险规则、待办事项、测试数量与本地部署状态不代表 v0.10.3；当前说明见 [文档导航](../../README.md)。

执行日期：2026-09-23（Asia/Shanghai）。

## Automated summary

| Gate | Result | Evidence |
|---|---|---|
| Diff hygiene | PASS | `git diff --check` 无输出 |
| Ruff | PASS | `All checks passed!` |
| Default SQLite/Fake pytest | PASS | `162 passed, 4 skipped in 1.46s` |
| PostgreSQL integration | PASS | `4 passed, 162 deselected in 0.45s` |
| Alembic migration | PASS | product 与 `banking_test` 均由 0004 升级至 0005 |
| Report Golden integration | PASS | persisted/GET deterministic core 与 committed fixture 全等 |
| OpenAPI generation | PASS | running API → generated TypeScript schema |
| Frontend lint | PASS | ESLint |
| Frontend typecheck | PASS | `tsc --noEmit` |
| Frontend production build | PASS | Next build，`/reports` 与 `/reports/[reportId]` 均生成 |
| Docker Compose | PASS | API/Web build and up；PostgreSQL healthy |
| API health/version | PASS | health OK，OpenAPI version `0.3.4` |
| Real DeepSeek product smoke | PASS | route → agent → tools → skill → report → GET → confirmation |
| Browser E2E | PASS | create、ReportCard、detail、refresh、history list 均通过 |

默认 suite 的 4 个 skip 是显式 opt-in 的 PostgreSQL tests，并在独立 PostgreSQL gate 中全部执行通过。

## Backend coverage

- Report create/read/list 与 pagination validation。
- 按用户 ownership 隔离，不泄漏其他用户资源。
- `(source_task_id, report_type, report_version)` 幂等。
- API 没有 Report mutation surface。
- provenance fields 与 canonical Snapshot hash 稳定。
- exact Decimal JSON 为 string。
- 普通 Financial `ANSWER` 不创建 Report。
- Skill input incomplete/failure 不创建 Report。
- persistence failure 不产生 `report.generated`，Task 不进入 `COMPLETED`。
- Artifact persistence 后才创建 confirmation 与完成 Task。
- Task output 包含 report reference。
- `report.generated` 不包含完整 content。
- mixed report + transfer prompt 不获得写权限。

## Golden GET Report assertions

| Metric | Exact JSON string | Display |
|---|---:|---:|
| total_income | `23800.00` | `¥23,800.00` |
| total_spending | `16547.30` | `¥16,547.30` |
| previous_spending | `9333.20` | `¥9,333.20` |
| absolute_change | `7214.10` | `+¥7,214.10` |
| percentage_change | `77.29503278618265975228217546` | `+77.3%` |
| FOOD change | `589.10` | `+¥589.10` |
| SHOPPING change | `2662.00` | `+¥2,662.00` |
| TRAVEL change | `4260.00` | `+¥4,260.00` |

整个 persisted report deterministic core 与 `mock_bank/data/golden_monthly_report_core.json` 精确比较，不使用 LLM correctness judge。

## Fake product E2E

输入：

```text
生成2026年8月份消费报告
```

验证：

```text
FINANCIAL_ANALYSIS / MONTHLY_REPORT
→ agent:financial-analysis
→ deterministic financial tools
→ FinancialAnalysisSnapshot
→ skill:monthly-spending-report@1
→ Report persisted
→ report.generated
→ one Assistant confirmation
→ Task COMPLETED
```

Financial Agent 的中间自然语言答案没有作为第二条 Assistant Message 暴露。

## Real DeepSeek product smoke

脱敏结果：

```text
route=FINANCIAL_ANALYSIS
requested_output=MONTHLY_REPORT
agent_id=agent:financial-analysis
tool_evidence=[
  transaction.spending_summary,
  transaction.category_breakdown,
  transaction.compare_periods,
  transaction.top_transactions(limit=5)
]
skill=skill:monthly-spending-report@1
report.generated=true
GET_report=true
golden_core_equal=true
assistant="2026年8月消费报告已生成。"
```

Smoke 未输出 API Key、完整 Prompt 或 Chain-of-Thought。

## Browser E2E

在真实 Docker Compose + DeepSeek 产品环境验证：

- 在 Agent Workspace 提交“生成一份2026年8月份消费报告”。
- 显示分析与生成报告进度。
- 只出现最终 confirmation。
- Conversation ReportCard 显示 `2026年8月消费报告` 与 `¥16,547.30`。
- `/reports/{id}` 以 Structured UI 展示 Overview、`+¥7,214.10`、`+77.3%`、分类、洞察、Top 5 与 COMPLETE。
- 刷新详情后 Artifact 仍可恢复。
- `/reports` 可查看历史报告并重新打开。
- `TRANSPORT` 显示为中文“通勤”。

## Frontend production build routes

```text
/                     4.38 kB
/reports              2.28 kB
/reports/[reportId]   3.48 kB
```

Frontend 使用生成的 `ReportResponse`、`MonthlySpendingReport` 和 `ReportListItem` 类型；没有自行计算或格式化金融数字。
