# Monthly Spending Report Skill

`skill:monthly-spending-report` 只接受已验证的 `FinancialAnalysisSnapshot`。
它不读取 Conversation history、不接受 raw transactions、不调用 Tool，
也不重新计算金融指标。

执行边界：

```text
FinancialAnalysisSnapshot
    -> Python deterministic report core + display formatting
    -> LLM headline/insights JSON (tools=[])
    -> Pydantic + evidence + numeric-leak validation
    -> MonthlySpendingReport
```

数值、排序和展示格式属于 Python；LLM 只生成不含数字的中文文字洞察。
