# Golden Financial Data v0.3.1

Status: `SUPERSEDED BY v0.3.2 INCOME SEMANTIC CORRECTION`

本文档记录 `mock_bank/data/golden_financial_metrics.json` 的人工可审阅摘要。Fixture 由一次性独立 reference script `scripts/generate_golden_financial_metrics.py` 生成后固定提交；production tests 只读取固定 fixture 并与 `FinancialAnalyticsService` 的实际计算结果精确比较，不在测试期间重新生成 expected values。

## 固定计算规则

- Period 是 `YYYY-MM` 自然月，区间左闭右开。
- 有效 status 只有 `POSTED`。
- v0.3.2 起 Income 是有效 `CREDIT` 且 `category != TRANSFER`；内部转入不解释为收入。
- Spending 是有效 `DEBIT` 且 `category != TRANSFER`。
- 全部金额使用 `Decimal`，不使用 `float`。
- 当前 Golden 数据币种是 `CNY`，不做汇率换算。
- Category 按 amount 降序、category 字符串稳定排序；Top transactions 按 amount 降序、occurred_at 升序、transaction_id 升序。

## 月度摘要

| Period | Total income | Total spending | Income count | Spending count |
|---|---:|---:|---:|---:|
| 2026-07 | 23800.00 | 9333.20 | 1 | 33 |
| 2026-08 | 23800.00 | 16547.30 | 1 | 45 |

7 月 raw posted debit 总额是 `14333.20`，其中 `5000.00` 是账户间 `TRANSFER`；Golden Spending 为 `9333.20`，明确验证内部转账未计入消费。

## Category breakdown

| Category | 2026-07 | 2026-08 | Jul → Aug absolute change | Percentage change |
|---|---:|---:|---:|---:|
| ENTERTAINMENT | 136.00 | 136.00 | 0.00 | 0% |
| FOOD | 416.20 | 1005.30 | 589.10 | 141.5425276309466602594906295% |
| HEALTH | 320.00 | 0 | -320.00 | -100% |
| HOUSING | 6200.00 | 6200.00 | 0.00 | 0% |
| OTHER | 32.00 | 55.00 | 23.00 | 71.87500% |
| SHOPPING | 1683.00 | 4345.00 | 2662.00 | 158.1699346405228758169934641% |
| SUBSCRIPTION | 149.00 | 149.00 | 0.00 | 0% |
| TRANSPORT | 128.00 | 128.00 | 0.00 | 0% |
| TRAVEL | 0 | 4260.00 | 4260.00 | `null` |
| UTILITIES | 269.00 | 269.00 | 0.00 | 0% |

8 月 category 按金额排序为：`HOUSING 6200.00`、`SHOPPING 4345.00`、`TRAVEL 4260.00`、`FOOD 1005.30`、`UTILITIES 269.00`、`SUBSCRIPTION 149.00`、`ENTERTAINMENT 136.00`、`TRANSPORT 128.00`、`OTHER 55.00`。

## Jul → Aug total comparison

```text
current_spending    = 16547.30
previous_spending   = 9333.20
absolute_change     = 7214.10
percentage_change   = 77.29503278618265975228217546
currency            = CNY
```

## 2026-08 Top 5

| Rank | Transaction | Date/time UTC | Category | Amount | Account |
|---:|---|---|---|---:|---|
| 1 | txn_0014 / 月租 | 2026-08-03T12:14:00Z | HOUSING | 6200.00 | acc_salary |
| 2 | txn_0113 / 家用电器（大额） | 2026-08-22T12:53:00Z | SHOPPING | 4200.00 | acc_credit |
| 3 | txn_0116 / 酒店 | 2026-08-05T12:56:00Z | TRAVEL | 1280.00 | acc_travel |
| 4 | txn_0119 / 酒店续住 | 2026-08-08T12:59:00Z | TRAVEL | 980.00 | acc_travel |
| 5 | txn_0115 / 往返交通 | 2026-08-04T12:55:00Z | TRAVEL | 680.00 | acc_travel |

Fixture 还固定了 7/8 月的全部 category share、transaction counts 与 7 月 Top 5，详细值以 JSON fixture 为准。
