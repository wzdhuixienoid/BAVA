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

## Wealth Recommendation Skill

`skill:wealth-recommendation` 已注册到应用 SkillRegistry，输入为通过校验的
`WealthAnalysis`，输出为 `WealthCustomerResponse`；工具白名单为空。它只组织
后端已经确定的候选、优势和限制，不改变排序、适当性或交易权限，不计算金融费用。
HTTP 与顾问路径共用这个呈现步骤；模型按事实引用的正文契约生成解释，失败则降级。

写作顺序为：回应本次用途与预算 → 说明一个实际产品差异 → 说明影响选择的限制
→ 提出最有影响的少量问题。不要把缺少预算当作冲突，不把风险承受等级当作购买目标，
不输出工具、内部推导栏目或授权流程。追求较高收益只能作为用户目标，不能证明某款
未来收益更高。事实不足时保留判断边界，不推断 Mock 产品资产配置。

本次核验参考：[商务部政策法规库转载《金融机构产品适当性管理办法》](https://policy.mofcom.gov.cn/claw/clawContent.shtml?id=103294)，
来源为国家金融监督管理总局令2025年第7号，2026-10-11读取全文。第2、25条强调需求、
财务状况、目标、期限及可接受损失；第31条强调通俗解释风险、损失和费用。本项目采用
这些作为沟通原则，不把项目测评、Mock 日历或交易规则称为法规统一标准。
监管原始网页与工行旧投教链接本次403，未以搜索摘要新增正式知识条目；现有知识内容未变。

产品目录与推荐分开：目录不使用问卷目标筛选或排名，不继承历史投资需求；
推荐引用问卷目标时说明来源，不用“这次也想……”暗示新的授权或已确认偏好。
呈现具体优势时同时保留产品限制和费用，不能只赞扬第一名。未来收益未知，客户自行选择。

## 类型与完整调用清单

本目录保存三个标准 Agent Skills 包的 Python 绑定实现，分别对应 agent_skills 下的 monthly-spending-report、transaction-anomaly-analysis 和 wealth-recommendation。每个包具有 SKILL.md 与 scripts/run.py，实例通过统一 Catalog 校验绑定契约。三个业务 Skill 均登记在应用 SkillRegistry；报告专用 SkillExecutor 只执行报告契约，其他呈现步骤由业务服务调用。`skill:transaction-anomaly-analysis` 基于已核验异常快照组织消费核对提示与完整说明，无模型和工具调用。

实际调用位置、八个标准 Agent Skills 包及修复记录见 [Skill 使用与审计](../../../../../docs/architecture/skills.md)。
