# Agents：只读业务执行者

## 职责

Agent 根据请求选择白名单内的查询工具并解释可信事实。模型工具循环由运行时驱动，AgentDefinition 保存稳定身份、Skill 绑定和能力上限；它不是提交资金的 Workflow，也不是组合高层能力的 Plan。

开发／测试环境登记以下三个 Agent，production 不登记 Mock 理财 Agent。注册及权限以 main.create_app 和 AgentRegistry 为准。

| Agent | ID | 职责 | 详细说明 |
| --- | --- | --- | --- |
| PersonalBankingAgent | `agent:personal-banking` | 账户、余额、收款人、账单与消费分析；三种请求配置共享一个身份 | [个人银行](personal-banking.md) |
| SubscriptionAnalysisAgent | `agent:subscription-analysis` | 周期费用、续费、涨价及可管理性解释 | [订阅分析](subscription-analysis.md) |
| WealthAdvisorAgent | `agent:wealth-advisor` | 模拟理财目录、推荐、比较、资料、持仓与订单解释 | [理财顾问](wealth-advisor.md) |

## 共同执行契约

RequestRouter 和 TaskRunner 选择已注册执行者及本次配置，ContextBuilder 提供受用户／对话范围约束的上下文。运行时验证实际技能绑定，再执行有步数／调用预算的工具循环。LangGraph 是产品运行时，金融分析和理财路径固定使用它；Manual 是部分基础场景的参考实现，不是另一个业务 Agent。

全部 Agent 仅获准 R1 读取。ToolExecutor 和 PolicyService 同时检查 Principal、caller、能力和类型；提示词、知识文档和模型输出都不能增加权限。LLM 可提取意图，但不能消费 Approval、代填测评或提交资金。需要取消、恢复、转账或申赎时转到对应 [Workflow](../workflows.md)。

## 结果与协作

Task.output 按类型保存可信查询结果、分析快照和展示内容，Message 保存客户答复，Event 保存执行与 Skill 元数据。Task COMPLETED 仅表示该次处理结束；Agent 回复不证明付款或结算成功。

三个 Agent 通过静态路由及受约束 [Plan](../plans.md) 组合，不互相自主委派。账户和消费的普通组合由 PersonalBankingAgent 一次完成；跨订阅／工作流的计划按已验证 DAG 执行。理财不是当前 Plan 注册能力。

历史 MinimalBankingAgent／FinancialAnalysisAgent 标识只用于旧任务读取与恢复，不是活跃 Agent。后台 Worker、Python Skill 绑定和 Workflow 也不计入 Agent 数量。

## 维护与验证

三个详情页采用相同章节，逐一说明真实身份、Skill、工具、持久结果、权限及失败处理。增加或删除注册 Agent 时同步本表、详情页、文档导航及覆盖测试；不能只改展示名称。

源码：[登记与生命周期](../../../apps/api/src/banking_api/main.py)、[AgentRegistry](../../../apps/api/src/banking_api/registries/agent_registry.py)、[AgentDefinition](../../../apps/api/src/banking_api/agents/models.py)。校验方法见 [测试指南](../../development/testing.md)。
