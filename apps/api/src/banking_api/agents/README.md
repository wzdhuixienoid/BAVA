# Agent

应用版本 0.11.3。当前登记 PersonalBankingAgent、SubscriptionAnalysisAgent、WealthAdvisorAgent 三个只读 Agent。

PersonalBankingAgent 使用统一身份 agent:personal-banking，执行前选择 ACCOUNT、SPENDING、COMBINED 配置，分别加载 banking-assistance、financial-analysis 或两者。只有报告请求额外加载 report-source.md；纯账户查询不加载消费规则。Tool 权限按所选配置校验，完整异常工具仍须本轮明确要求。资金提交和结算不向 Agent 开放。

旧 MinimalBankingAgent 与 FinancialAnalysisAgent 定义已移除，仅在兼容映射中保留历史 Task 标识。计划 ACCOUNT_QUERY、FINANCIAL_ANALYSIS 两种高层能力继续分开，但由同一个 Agent 按相应配置执行。详见 [个人银行 Agent](../../../../../docs/architecture/personal-banking.md)。
