# Plan：受约束高层编排

## 职责与能力

Plan 组合已有高层能力，保存有限 DAG 和步骤状态；Planner 不能创建任意工具、编写代码或直接提交资金。普通账户加消费查询由 PersonalBankingAgent 一次执行，不为单一 Agent 请求强造计划。

| 高层能力 | 执行者 | 事实／业务 |
| --- | --- | --- |
| ACCOUNT_QUERY | PersonalBankingAgent／ACCOUNT | 账户和余额等可信结果 |
| FINANCIAL_ANALYSIS | PersonalBankingAgent／SPENDING | 消费汇总及分类 |
| SUBSCRIPTION_ANALYSIS | SubscriptionAnalysisAgent | 订阅费用快照 |
| TRANSFER_WORKFLOW | workflow:transfer | 进入转账核对及授权 |
| SUBSCRIPTION_CANCEL_WORKFLOW | workflow:subscription-cancel | 进入取消确认 |
| SUBSCRIPTION_RESUME_WORKFLOW | workflow:subscription-resume | 进入恢复确认及强验证 |

能力表是静态注册，不是所有工具的集合。报告、AA 与理财交易未注册为当前 Plan 能力。

## 验证与条件

ConstrainedPlanner 生成 proposal，PlanValidator 校验能力、依赖、环、步骤数、条件与单写限制。最多 8 步、2 个条件、一个写工作流；不支持 ELSE、嵌套条件、AND／OR、循环、多笔写业务或动态重规划。

条件只有余额、月消费、订阅月成本“不少于”明确阈值。阈值必须被原始请求的对应条件从句支持，使用 Decimal 字符串；不能从转账金额推导余额阈值，也不能替“足够”“花太多”猜金额。币种来自原文或可信源唯一币种。

ConditionEvaluator 从对应源步骤的类型化结果读取值，记录 source_output_hash、比较值、阈值、币种和判断时间。FALSE 跳过被保护步骤，不创建写业务；TRUE 仍进入原工作流的确认和强验证。条件不触发额外金融权限。

## 持久执行与用户控制

Plan、PlanStep、依赖及 ConditionDecision 保存数据库，TaskRunner／PlanExecutionService 按依赖和 ordinal 推进 ready steps。等待用户或外部状态时保存关联工作流，恢复复用原计划／Operation；不重新规划或复制扣款。

“转为手动处理”把计划置为 PAUSED，失效当前 Task lease 并暂停自动编排；不撤销已有金融操作。“继续自动执行”恢复原 DAG。

回退只允许目标及全部后继均为只读／条件且没有关联工作流。清除受影响查询结果后重新执行原依赖，不提供资金撤销，也不跨写步骤回退。Plan 完成只表示编排结束，资金结果以各 Workflow／Operation 为准。

## 失败与验证

未注册能力、非法条件和多笔写请求被拒绝，不丢掉条件执行部分付款。源查询失败不能视为条件为 TRUE；缺失／不可信阈值要求补充。跨用户读取和用户操作受到归属与版本／租约检查。

源码：[能力登记](../../apps/api/src/banking_api/planning/registry.py)、[模型](../../apps/api/src/banking_api/planning/models.py)、[验证](../../apps/api/src/banking_api/planning/validator.py)、[阈值 grounding](../../apps/api/src/banking_api/planning/threshold_grounding.py)、[执行](../../apps/api/src/banking_api/application/plan_execution_service.py)、[用户动作](../../apps/api/src/banking_api/application/plan_service.py)。

测试覆盖 DAG、条件来源、明确阈值、FALSE 无写操作、等待／重启、接管、只读回退及 lease 并发。用户交互见 [多步骤任务](../guides/plans.md)，计算和授权见 [算法](algorithms.md) 与 [安全](security.md)。
