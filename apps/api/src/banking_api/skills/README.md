# Python 业务 Skill 绑定

本目录保存三个标准 Agent Skills 包的确定性实现，不是另一套技能格式。

| 实现 | 输入与输出 | 边界 |
| --- | --- | --- |
| MonthlySpendingReportSkill | FinancialAnalysisSnapshot → 报告核心及展示字段 | 不重查原始流水；SkillExecutor 校验模型草稿，并从核心事实确定性生成客户可见解释，tools=[] |
| TransactionAnomalyAnalysisSkill | 已核验异常快照 → 完整说明或 SpendingReview | 不重新检测，无模型／工具／数据库写入 |
| WealthRecommendationSkill | 已校验 WealthAnalysis → WealthCustomerResponse | 不改资格、排序、费用或授权；供确定性展示及模型降级 |

三个定义均登记至 SkillRegistry，绑定包内 metadata、输入／输出类型和契约版本。CLI 在相应包的 scripts/run.py，通过 JSON stdin／stdout 执行，不提交金融交易。业务 ID 与 import 路径保持稳定，资源版本独立管理。

完整包清单、实际调用、加载与验证见 [Agent Skills](../../../../../docs/architecture/skills.md)；包维护入口见 [agent_skills](../agent_skills/README.md)。
