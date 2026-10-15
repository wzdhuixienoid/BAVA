---
name: transaction-anomaly-analysis
description: 根据后端异常检测快照生成消费核对提示和异常明细说明；用于异常分析与消费报告中的核对部分。
metadata:
  version: "0.12.3"
  runtime: "banking-api"
  requirements: "Python >=3.12; banking-api installed"
  script-output-schema: "AnomalyAnalysisAnswer"
  business-skill-id: "skill:transaction-anomaly-analysis"
  contract-version: "1"
  input-schema: "TransactionAnomalySnapshot"
  output-schema: "AnomalyAnalysisAnswer"
---

只解释已经验证的异常检测快照，不依据原始流水重新检测或改变规则。异常提示不代表已确认欺诈，未检出不代表排除所有风险。保留样本不足、数据覆盖不足和有界展示提示。

金额、时间、排序和说明由绑定的 Python 实现产生。用 [Python 入口](scripts/run.py) 生成完整说明，--review 生成简短消费核对提示。此入口没有模型、工具、数据库或金融写权限。
