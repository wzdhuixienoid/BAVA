# 历史档案：Golden Financial Data v0.3.2

> 历史材料，保留原记录日期、版本和结论。旧风险规则、待办事项、测试数量与本地部署状态不代表 v0.10.3；当前说明见 [文档导航](../../README.md)。

Status: `COMMITTED FIXTURE`

v0.3.2 保留 v0.3.1 的 Spending、category、comparison 和 Top N 规则，只修正 Income 语义：

```text
Income = POSTED + CREDIT + category != TRANSFER
```

因此 2026-07 的 `5000.00 CNY` 内部转入不再解释为收入。

## 固定规则

- 有效 transaction status：`POSTED`。
- Income：`CREDIT` 且排除 `TRANSFER`。
- Spending：`DEBIT` 且排除 `TRANSFER`。
- 全部金额、share、absolute change 和 percentage change 使用 `Decimal`。
- Period：`YYYY-MM` UTC 自然月，左闭右开。
- 不做汇率换算；多币种聚合 fail closed。
- Fixture version：`0.3.2`。

## 月度摘要

| Period | Total income | Income count | Total spending | Spending count | Currency |
|---|---:|---:|---:|---:|---|
| 2026-07 | 23800.00 | 1 | 9333.20 | 33 | CNY |
| 2026-08 | 23800.00 | 1 | 16547.30 | 45 | CNY |

## Jul → Aug 消费变化

```text
previous_spending = 9333.20
current_spending  = 16547.30
absolute_change   = 7214.10
percentage_change = 77.29503278618265975228217546
```

关键分类：

| Category | July | August | Absolute change | Percentage change |
|---|---:|---:|---:|---:|
| FOOD | 416.20 | 1005.30 | 589.10 | 141.5425276309466602594906295 |
| SHOPPING | 1683.00 | 4345.00 | 2662.00 | 158.1699346405228758169934641 |
| TRAVEL | 0 | 4260.00 | 4260.00 | `null` |

## 2026-08 Top 5

| Rank | Transaction | Category | Amount | Account |
|---:|---|---|---:|---|
| 1 | txn_0014 / 月租 | HOUSING | 6200.00 | acc_salary |
| 2 | txn_0113 / 家用电器（大额） | SHOPPING | 4200.00 | acc_credit |
| 3 | txn_0116 / 酒店 | TRAVEL | 1280.00 | acc_travel |
| 4 | txn_0119 / 酒店续住 | TRAVEL | 980.00 | acc_travel |
| 5 | txn_0115 / 往返交通 | TRAVEL | 680.00 | acc_travel |

`test_financial_golden.py` 和 `test_financial_agent_grounding.py` 都直接读取 committed JSON，测试期间不生成 expected values。
