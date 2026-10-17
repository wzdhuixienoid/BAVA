# 只读业务 Agents

开发／测试登记 PersonalBankingAgent、SubscriptionAnalysisAgent、WealthAdvisorAgent，生产不登记 Mock 理财 Agent。定义固定技能绑定与能力上限，运行时按请求缩小权限，不承担金融授权或提交。

PersonalBankingAgent 共享一个身份，按 ACCOUNT／SPENDING／COMBINED 加载账户与消费技能。订阅 Agent 仅分析周期费用，理财 Agent 查询目录、推荐、比较、资料及本人持仓／订单。

旧任务标识只保留显式读取和恢复映射，不另登记旧 Agent。三个 Agent 的职责、技能、工具和持久结果见 [Agents 总览](../../../../../docs/architecture/agents/README.md)，整体职责见 [系统架构](../../../../../docs/architecture/system.md)。
