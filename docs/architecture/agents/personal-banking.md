# PersonalBankingAgent

## 职责与入口

`agent:personal-banking` 统一处理账户、余额、收款人、已入账账单及消费分析。开发、测试和生产装配均登记该身份；ACCOUNT、SPENDING、COMBINED 是同一 Agent 的执行配置。

RequestRouter 的 ACCOUNT_QUERY、FINANCIAL_ANALYSIS、PERSONAL_BANKING 路由选择对应配置。“查余额，再分析消费”可一次完成；条件和跨订阅／工作流组合进入 Plan。

## Skill 与工具

| 配置 | 标准 Skill 与资源 | 能力上限 |
| --- | --- | --- |
| ACCOUNT | banking-assistance | `account.list`、`account.get_balance`、`account.statement`、`payee.list`、`payee.search` |
| SPENDING | financial-analysis、analysis-rules.md | `account.list`、`transaction.spending_summary`、`transaction.category_breakdown`、`transaction.compare_periods`、`transaction.top_transactions`、`transaction.detect_anomalies` |
| COMBINED | 上述两个 Skill | 两种配置的并集，共十项 |

普通消费请求去掉完整异常工具，本次明确要求才开放；报告额外加载 report-source.md，再由 monthly-spending-report Python 绑定与 SkillExecutor 生成并校验报告。transaction-anomaly-analysis 组织已核验异常说明，不重新计算规则。

每次执行先缩小工具与技能范围，模型自行输出 COMBINED 或调用其他工具不能扩大权限。工具预算由运行时统一限制，可用一次列账户及逐卡余额查询完成四卡结果，不使用固定四次限制。

## 执行与结果

账户、收款人和账单分别保存 account_results、payee_results、statement_results；statement_queries 保存实际筛选。消费分析保存 analysis_snapshot，纯账户查询不生成空消费快照。余额与消费、报告或异常组合时，各类结果保留，当前余额不当作期间结余。

get_account_statement 与金融总览共用 AccountStatementService，只读已入账现金事实。默认近 30 天、每页 10 条、最多 50 条；支持北京时间自然年／月、日期区间、账户、方向、类别、来源及对手方／备注。Decimal 汇总在分页前完成，提供全期间分币种收支、笔数、对手方分组、解读及最近明细，前端不自行求和。

“下一页”只继承本人本对话最近完成账单查询的条件和 as_of；普通新查询不继承旧月份。Manual 和 LangGraph 共同约束明确方向和续页参数，模型遗漏／改写不改变可信范围。完整历史快照可派生展示，部分明细不能推断完整总额，不回写历史任务。

## 边界与失败处理

无转账提交、订阅管理或理财执行权限。待处理／失败转账、未来预约、续费提醒和理财冻结都不算已入账；只读账单不推进对账或结算。不同币种分别组织，消费分析排除转账及理财资产移动。

找不到匹配只说明所查期间没有已入账记录，不判定从未发起交易。已删除收款人的已入账历史仍可展示；银行未提供的转入方姓名不猜测。无足够证据、不明确对象或无效期间返回具体限制／补充问题。

Task.input.personal_banking_route 固定本次配置，恢复不重新分类；缺失或非法配置拒绝。旧 agent:minimal-banking／agent:financial-analysis 分别只兼容为 ACCOUNT／SPENDING，旧 MINIMAL_BANKING 路由仅兼容为 ACCOUNT_QUERY，不登记旧执行器。

## 源码与验证

[定义](../../../apps/api/src/banking_api/agents/personal_banking_agent.py)、[TaskRunner](../../../apps/api/src/banking_api/runtime/task_runner.py)、[账单服务](../../../apps/api/src/banking_api/application/account_statement_service.py)。

验证入口：test_personal_banking_integration.py、test_statement_tool.py、test_statement_analysis.py、test_account_statement.py 及两个运行时、报告、条件和安全回归。使用方式见 [账户与账单](../../guides/financial-analysis.md)，检查命令见 [测试](../../development/testing.md)。
