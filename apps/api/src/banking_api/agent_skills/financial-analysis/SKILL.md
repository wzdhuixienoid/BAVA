---
name: financial-analysis
description: 分析本人消费结构、期间变化及异常交易；消费分析和报告数据采集时使用。
metadata:
  version: "0.12.3"
  runtime: "banking-api"
---

以银行聚合事实分析用户明确指定的期间与账户。金额、比例、日期及异常判断由后端产生，不能自行计算或扩展查询范围。

每次分析读取 [消费分析规则](references/analysis-rules.md)。用户明确要求报告时，额外读取 [报告数据采集](references/report-source.md)；文字报告由独立的 monthly-spending-report 技能生成。
