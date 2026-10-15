---
name: wealth-recommendation
description: 把已校验理财分析呈现为客户答复；用于确定性呈现和模型说明核验失败时的降级，包括申购或赎回字段补全。
metadata:
  version: "0.12.3"
  runtime: "banking-api"
  requirements: "Python >=3.12; banking-api installed"
  script-output-schema: "WealthCustomerResponse"
  business-skill-id: "skill:wealth-recommendation"
  contract-version: "1"
  input-schema: "WealthAnalysis"
  output-schema: "WealthCustomerResponse"
---

保留后端确定的候选顺序、适当性、事实与证据。直接回应本次用途，解释策略与风险取舍；不预测收益、不计算费用、不扩大资格。客观介绍、知识问答和交易准备遵循各自的输入模式。

申购使用元，赎回使用份；只询问已验证输入中尚缺的交易字段，不重新要求赎回的购买测评。用 [Python 入口](scripts/run.py) 输出客户呈现 DTO，缺失字段和展示数值由绑定的 Python 实现确定。无模型、工具及金融写权限。
