---
name: wealth-trade-assistance
description: 用户明确选择模拟理财申购或赎回时，续接产品、本人账户和精确金额或份额输入，进入已有核对工作流。
metadata:
  version: "0.12.3"
---

# 理财交易协助
回应已经选中的产品，只补全交易必要字段。已解析的产品、本人账户和数量只需核对，不重复询问；缺失字段以提供的 trade_fields 为准。预算可预填，仍需本人核对。不要继续问推荐期限或最大亏损，不将自然语言确认当授权，不宣称已扣款。身份、金融事实与Workflow由后端核验。

使用 [输入与工作流](references/input-and-workflow.md)，不得使用申购提交工具。
