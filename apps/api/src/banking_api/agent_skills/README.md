# 应用 Agent Skills

应用交付版本为 **0.11.3**。banking-assistance 资源版本为 **0.12.7**、financial-analysis 为 **0.12.4**，其他包为 **0.12.3**；资源版本独立用于绑定和 hash 审计，不作为网页或 API 版本。

所有应用业务 agent 与业务 Skill 均绑定 [Agent Skills 规范](https://agentskills.io/specification) 的技能包。指令集中在 `SKILL.md` 和按场景读取的 references；Python 模块保存权限白名单、计算、类型校验及工作流执行。

| 标准技能包 | 绑定路径 |
| --- | --- |
| banking-assistance | PersonalBankingAgent：ACCOUNT / COMBINED |
| financial-analysis | PersonalBankingAgent：SPENDING / COMBINED，报告模式额外加载 report-source.md |
| subscription-analysis | SubscriptionAnalysisAgent |
| wealth-advisory | WealthAdvisorAgent；按推荐、比较、定位、知识模式加载资料 |
| wealth-trade-assistance | 申购/赎回准备，续接已有 Workflow |
| monthly-spending-report | MonthlySpendingReportSkill / SkillExecutor |
| transaction-anomaly-analysis | TransactionAnomalyAnalysisSkill，完整说明或简短核对提示 |
| wealth-recommendation | WealthRecommendationSkill，确定性呈现与降级 |

每个包的目录名与 name 一致，包含 YAML name/description 和 metadata.version。metadata 中的业务 ID、输入输出 schema、契约版本是本应用绑定约定；标准本身不要求这些字段。

三个 Python 业务技能提供 `scripts/run.py`：通过 stdin 接受 JSON，stdout 返回 JSON，错误使用 stderr 并退出 2。需要 Python 3.12+ 与已安装的 banking-api 包。消费报告入口只返回报告核心，不调用模型；文字生成仍由应用 SkillExecutor 执行。异常入口支持 --review，理财呈现入口返回客户 DTO。三个入口均不写数据库或执行金融交易。

AgentRegistry 拒绝没有标准技能、指令不包含绑定技能或 hash 不一致的 agent；SkillRegistry 拒绝业务 ID、输入输出类型、契约版本或工具权限与包不匹配的实现。Manual 与 LangGraph 在调用模型或工具前再次校验绑定；动态报告/理财模式保留实际激活的技能。Manual 与 LangGraph 的 agent.run.started 事件记录实际技能版本及资源 hash；报告和异常执行事件附业务技能包元数据。加载或执行技能资源不会扩大应用 Policy 的权限。

加载器安全解析 YAML，拒绝重复键、未知字段、空描述、无效 metadata、未声明/越界引用；脚本只登记 hash，不加载为模型指令或自动授予 Shell 权限。目录元数据用于发现，模型只接收所选技能正文与本次需要的 references。可信包采用进程内加载快照，更新包后重启服务。

修改资源时更新技能资源版本，运行 `test_agent_skill_catalog`、`test_standard_skill_bindings`、业务回归和真实模型 smoke；对每个包运行 quick_validate。镜像内检查 discover、activate_named 和代理/业务契约绑定，验证部署资源完整。
