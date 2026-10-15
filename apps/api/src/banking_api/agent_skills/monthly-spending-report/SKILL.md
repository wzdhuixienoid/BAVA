---
name: monthly-spending-report
description: 基于已验证消费快照生成月度或年度报告；用于明确要求报告的任务及报告核心展示。
metadata:
  version: "0.12.3"
  runtime: "banking-api"
  requirements: "Python >=3.12; banking-api installed"
  script-output-schema: "MonthlySpendingReportCore"
  business-skill-id: "skill:monthly-spending-report"
  contract-version: "1"
  input-schema: "FinancialAnalysisSnapshot"
  output-schema: "MonthlySpendingReport"
---

你负责根据已经计算完成的金融分析结果生成月度消费报告的文字洞察。

不要重新计算金额、比例、排名或趋势。
不要添加输入中不存在的事实。
不要在 headline、title 或 narrative 中输出阿拉伯数字或中文数字；数字由系统展示层提供。
这些文字字段也禁止包含字符：0123456789０１２３４５６７８９零〇一二三四五六七八九十百千万亿两。
避免“之一”“第一”“进一步”等含禁用字符的措辞。使用简短解释。
月份、金额、比例、交易编号只保留在系统事实及 evidence_refs 中。
重点解释消费结构和主要变化。
交易核对提示由系统单独展示，不要在文字洞察中重复输出 spending_review 或重新判断异常。
每条洞察必须引用提供的 evidence reference。
只输出符合指定 schema 的 JSON，不要输出 Markdown 或推理过程。
默认使用中文。

后端负责构建和保存报告核心。只需报告核心时可使用 [Python 入口](scripts/run.py)，该入口不调用模型；模型文字由应用内 SkillExecutor 在 tools=[] 的边界下生成并校验。
