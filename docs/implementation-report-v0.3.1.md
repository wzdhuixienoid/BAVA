# AI Banking Agent — Financial Data & Deterministic Analytics v0.3.1

Status: `IMPLEMENTED AND VERIFIED`

实施日期：2026-09-22。本轮仅建设 Synthetic Transactions → Financial Data Layer → Deterministic Analytics → Typed Read-only Tools → Golden Evaluation。没有新增 Agent、Skill、Report Artifact、Chart、API 或 UI；`ManualAgentRuntime` 未修改。

## 1. Files changed

新增：

- `banking_api/financial/{__init__,models,errors,analytics_service}.py`
- 四个 `banking_api/tools/banking/` typed tool builder
- `mock_bank/data/golden_financial_metrics.json`
- `scripts/generate_golden_financial_metrics.py`
- `test_financial_analytics.py`、`test_financial_tools.py`、`test_financial_golden.py`
- v0.3.1 Golden、Implementation、Repository Tree 和 Test Results 文档

修改：

- `MockBankService` 新增仅供内部 domain service 使用的 synthetic transaction reader。
- `ToolExecutor` 在既有执行边界映射 Financial Domain Error，未修改 Agent Runtime error mechanism。
- Tool exports/application Registry 注册四个新 capability。
- README、API package/app version 和 lockfile project version 更新为 `0.3.1`。

## 2. Financial calculation rules

- 所有 transaction amount、sum、difference、share 和 percentage 都使用 `Decimal`。
- Dataset amount 始终是正数；收支由 `direction` 区分。
- Period 严格使用 `YYYY-MM`，UTC 自然月左闭右开。
- Category share = category amount / total spending，在显式 precision 28 的 Decimal local context 内计算。
- Percentage change = `(current - previous) / previous * 100`；previous 为 0 时返回 `null`。
- Category breakdown 按 amount DESC，category ASC 作 stable tie-breaker。
- Top transactions 按 amount DESC、occurred_at ASC、transaction_id ASC，`limit` 由 schema 限制为 1..20。
- 同次 aggregation 的有效交易出现多币种时返回 `MIXED_CURRENCY_UNSUPPORTED`，不做汇率换算。

## 3. Spending definition

Spending 只包含 `status=POSTED`、`direction=DEBIT`、`category != TRANSFER` 的交易。房租、餐饮、通勤、水电通信、订阅、购物、旅行等均计入。内部转账 debit 不计入 Spending。

v0.3.2 语义修正：Income 为有效 `CREDIT` 且 `category != TRANSFER`，因此 7 月 `total_income=23800.00`。这条修正取代本报告初版对 Transfer Credit 的处理。

## 4. Transaction status rules

有效 status 通过常量 `VALID_TRANSACTION_STATUSES = frozenset({"POSTED"})` 显式固定。Pending 或任何其他 status 不进入分析。

## 5. Four Tool schemas

| Capability | Tool | Input | Output boundary |
|---|---|---|---|
| `transaction.spending_summary` | `get_spending_summary` | `month`, optional `account_ids` | totals/counts/currency |
| `transaction.category_breakdown` | `get_category_breakdown` | `month`, optional `account_ids` | aggregate category rows |
| `transaction.compare_periods` | `compare_spending_periods` | `month`, optional `account_ids` | current/previous totals and category changes |
| `transaction.top_transactions` | `get_top_transactions` | `month`, `limit=5`, optional `account_ids` | bounded Top N, maximum 20 |

全部 input/output 均为 Pydantic model。不存在 `transaction.search`，不返回整月 raw history。

## 6. Permission configuration

四个 Tool 均为 `R1_PRIVATE_READ`、`side_effect=false`，`allowed_callers={"agent:financial-analysis"}`。它们注册在现有 ToolRegistry，继续通过 PolicyService 和 ToolExecutor 执行。

`agent:minimal-banking` 的 allowed capabilities 仍只是 `account.list` 和 `account.get_balance`，因此 ContextBuilder 不向它暴露 financial tools，Policy 也会拒绝强制调用。本轮没有实现 `FinancialAnalysisAgent`。

## 7. Golden Dataset exact values

| Period | Income | Spending | Income tx | Spending tx |
|---|---:|---:|---:|---:|
| 2026-07 | 23800.00 | 9333.20 | 1 | 33 |
| 2026-08 | 23800.00 | 16547.30 | 1 | 45 |

8 月 breakdown：HOUSING `6200.00`，SHOPPING `4345.00`，TRAVEL `4260.00`，FOOD `1005.30`，UTILITIES `269.00`，SUBSCRIPTION `149.00`，ENTERTAINMENT `136.00`，TRANSPORT `128.00`，OTHER `55.00`。

8 月 Top 5 金额为 `6200.00`、`4200.00`、`1280.00`、`980.00`、`680.00`，对应 `txn_0014`、`txn_0113`、`txn_0116`、`txn_0119`、`txn_0115`。

## 8. Jul vs Aug exact comparison

```text
July spending       9333.20
August spending    16547.30
absolute change     7214.10
percentage change     77.29503278618265975228217546
```

## 9. FOOD/TRAVEL exact comparison

```text
FOOD:   416.20 -> 1005.30; absolute +589.10; +141.5425276309466602594906295%
TRAVEL:   0    -> 4260.00; absolute +4260.00; percentage null
```

## 10. Tests and results

- Preflight v0.2.2 baseline：`57 passed, 3 skipped`。
- v0.3.1 full SQLite/Fake suite：`99 passed, 3 skipped`。
- PostgreSQL marker suite：`3 passed, 99 deselected`。
- Ruff：PASS。
- Frontend ESLint / TypeScript / production build：PASS。
- Docker Compose API/Web build、PostgreSQL health、migration/checkpoint startup、API `/health`：PASS。
- 真实 DeepSeek LangGraph smoke：PASS。`deepseek-v4-flash` 完成账户列表、工资卡余额、写操作注入拒绝和不存在账户四个场景；API Key 未输出。

## 11. Known limitations

- v0.3.1 仅处理已提交 synthetic JSON，没有 transaction persistence/API。
- 不做汇率换算。
- 不做 anomaly detection、raw search、report 或 chart。
- Share 和 percentage 返回 precision 28 的 Decimal，显示层舍入规则留待产品层定义。

## 12. Deviations

- 代码中 mock data 的实际路径沿用现有 package layout：`apps/api/src/banking_api/mock_bank/data/`，而非新建仓库顶层 `mock_bank/data/`。
- 除上述路径对齐外，未发现功能或安全语义偏离。

## 13. Architecture questions

- v0.3.2 已明确 total income 排除 internal `TRANSFER` credit。
- 真实多币种业务需先定义 FX source、valuation timestamp 和 rounding policy，本轮明确 fail closed。
