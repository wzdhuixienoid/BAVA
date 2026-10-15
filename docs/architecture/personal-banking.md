# PersonalBankingAgent（应用 0.11.3）

2026-10-15 将原基础银行查询与消费分析的独立执行器整合为一个 `agent:personal-banking`。登记三个业务 Agent：PersonalBankingAgent、SubscriptionAnalysisAgent、WealthAdvisorAgent。资金提交、订阅取消/恢复、理财申赎与结算继续通过原 Workflow/Operation 执行。

## 按请求加载 Skill 和工具

| 路由 / 配置 | Skill | 工具范围 |
| --- | --- | --- |
| ACCOUNT_QUERY / ACCOUNT | banking-assistance | 账户、余额、账单、收款人列表/搜索，共五项 |
| FINANCIAL_ANALYSIS / SPENDING | financial-analysis + analysis-rules.md | 账户列表与五项消费分析；不开放余额、收款人 |
| PERSONAL_BANKING / COMBINED | 上述两个 Skill | 账户查询和消费分析所需能力，共十项上限 |

三种配置共享同一个 Agent ID，不登记为三个 Agent。注册定义保存能力上限，每次执行先选择具体配置，再将 Skill 正文、所需 references 和工具白名单送入模型。报告请求额外加载 report-source.md，报告文字继续由 monthly-spending-report Skill 生成。banking-assistance 资源版本为 0.12.7，financial-analysis 为 0.12.4（其余包仍 0.12.3），与应用版本独立。

普通消费请求移除完整异常工具；本轮明确要求异常时才允许。工具执行仍受 ToolExecutor / PolicyService 校验，模型自行选择某工具不会扩大白名单。模型单独返回 COMBINED 标签也不能为单一用途请求开启两种配置。

## 交互与结果

“先查工资卡余额，再分析八月消费”走一个 PersonalBankingAgent，不创建 Plan。条件请求、“先分析订阅再取消订阅”、跨工作流任务仍走原计划约束。

- 账户事实保存在 account_results，收款人保存在 payee_results，已入账账单保存在 statement_results，筛选保存在 statement_queries。
- get_account_statement 与金融总览共用 AccountStatementService；只查询实际入账，不调用会推进状态的对账工具。默认近30天，支持北京时间自然年/月、日期区间、账户、方向、类别、来源和对手方/备注，单页最多50条。
- 工具summary在分页前使用Decimal计算分币种转入/转出总额、笔数与对手方分组；answer保存按消费分析风格呈现的区间、总览、分组、解读与最近明细。网页复用同一正文，不在浏览器做金额计算。
- 历史完整快照可派生汇总展示，部分明细禁止推断完整总额；展示层不改写历史Task或Message。
- “下一页”只续接本人本对话最近已完成账单查询；复用原条件和 as_of，翻完明确说明。普通查询不继承旧月份。
- Manual与LangGraph执行层共同固定明确转入/转出方向，并对续页请求复用可信原条件；模型遗漏方向或改写分页参数不改变实际查询范围。
- 已删除的收款人仍可显示历史转出姓名；转入方姓名没有银行来源时仅标注转账收入，不猜姓名。
- 发生消费分析时保存 analysis_snapshot；纯账户请求不创建空消费快照。
- 组合请求保留两类事实；当前余额不等于某期间收入减支出，模型不自行计算余额合计或结余。
- 余额加报告：余额在报告外单独保存和说明，不进入报告的消费指标。
- 余额加异常：异常说明仍由确定性 Skill 组织，同时保留银行返回的余额说明，不因替换模型文字而丢掉账户结果。
- 工具预算由运行时统一限制，不沿用原消费指令的固定四次限制。四张卡查询可完成一次列账户及四次余额调用；同一分析工具不重复调用。

## 计划、重启与历史兼容

计划中的 ACCOUNT_QUERY、FINANCIAL_ANALYSIS 继续作为不同高层能力。两者映射同一执行器，但执行时分别选择 ACCOUNT/SPENDING 配置；条件判断仍使用对应的结构化来源。合并执行器不合并两种事实类型或授权边界。

新任务将路由配置固定在 Task.input.personal_banking_route。恢复时使用该值，不重新让模型分类；缺失或不合法配置拒绝执行。无新增迁移，使用已有 JSON 字段，数据库 head 仍为 0034。

旧 agent:minimal-banking、agent:financial-analysis 只保留显式兼容映射，分别恢复为 ACCOUNT/SPENDING；历史 Task、结果与事件不改写。旧 MINIMAL_BANKING 路由字符串作为输入兼容为 ACCOUNT_QUERY。旧 Agent 源文件与活跃注册已删除，未保留第二套实现。

## 验证

`test_personal_banking_integration.py` 经对话接口、TaskRunner、运行时及真实确定性工具验证配置隔离、四卡余额、组合消费、报告、异常、旧任务恢复和配置缺失拒绝。原账户、金融、报告、计划条件、安全及 PostgreSQL 套件同步回归。最终执行证据见 [当前更新说明](../releases/release-notes-v0.11.3.md)。
