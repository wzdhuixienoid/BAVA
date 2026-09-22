# Golden Monthly Spending Report Core v0.3.3

Status: `COMMITTED FIXTURE`

固定 fixture：`apps/api/src/banking_api/mock_bank/data/golden_monthly_report_core.json`。它仅保存由 Python 构建的 deterministic report core，不固定 LLM headline 或 insights。测试期间只读取该文件，不动态生成 expected result。

## Source

```text
golden_financial_metrics.json#2026-08
scope.account_ids = []  # 全部允许账户
report_version = 1
data_quality.status = COMPLETE
```

## Overview

| Field | Exact value | Display |
|---|---:|---:|
| total_income | 23800.00 | ¥23,800.00 |
| total_spending | 16547.30 | ¥16,547.30 |
| transaction_count | 45 | 45 |
| currency | CNY | CNY |

## Period comparison

| Field | Exact value | Display |
|---|---:|---:|
| previous_spending | 9333.20 | ¥9,333.20 |
| absolute_change | 7214.10 | +¥7,214.10 |
| percentage_change | 77.29503278618265975228217546 | +77.3% |

## Grounding categories

| Category | Exact change | Change display | Share display |
|---|---:|---:|---:|
| FOOD | 589.10 | +¥589.10 | 6.1% |
| SHOPPING | 2662.00 | +¥2,662.00 | 26.3% |
| TRAVEL | 4260.00 | +¥4,260.00 | 25.7% |

TRAVEL 上期值为零，精确 `percentage_change` 是 `null`，展示值是 `—`。Category 顺序原样保留 Snapshot 中的 deterministic amount-descending 顺序。

## Top transactions

Top N 原样保留 Snapshot 中的有界列表：

```text
txn_0014, txn_0113, txn_0116, txn_0119, txn_0115
```

每项保留 transaction ID、merchant、description、category、exact Decimal amount、Python-formatted amount、occurred_at 和 account_id。
