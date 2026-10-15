# Agent

账户、消费、订阅和理财四类只读 Agent 分别绑定 banking-assistance、financial-analysis、subscription-analysis 和 wealth-advisory 标准技能包。指令由 agent_skills 提供，注册与运行前校验绑定和资源 hash；派生报告及理财场景按需加载 references。理财开关关闭时不注册 WealthAdvisorAgent。

产品 runtime 使用 LangGraph。Agent 只读工具白名单由 ToolRegistry 和 PolicyService 强制执行；金额、排名和结构化结果由确定性服务计算。完整调用与验证见 [Skill 审计](../../../../../docs/architecture/skills.md)。
