# SubscriptionAnalysisAgent

## 职责与入口

`agent:subscription-analysis` 解释本人周期扣费、月度／年度费用、涨价、下次续费及管理方式。开发、测试和生产均登记；SUBSCRIPTION_ANALYSIS 路由及 Plan 中的订阅分析步骤使用它。

典型请求是“我有哪些订阅”“每月订阅花多少”“最近有没有涨价”。取消／恢复意图由路由进入业务工作流，不由本 Agent 执行。

## Skill 与工具

唯一标准 Skill 是 subscription-analysis，唯一能力是 `subscription.analyze`，对应 analyze_subscriptions，R1_PRIVATE_READ、无金融副作用。

技能要求金额、周期、涨价、续费及可取消性来自工具；不能靠模型重识别订阅、计算金额或推断用户没有使用服务。工具结合确定性 SubscriptionDetector、合成历史、合同状态和已记录的扣费事实组织 SubscriptionAnalysisSnapshot。

“可在这里管理”和“需要到商户管理”依据 Provider 能力区分；仅检测到周期交易不产生站内管理权或扣费授权。

## 执行与结果

TaskRunner 使用该 Agent 的 Skill 指令与唯一白名单查询工具。查询前需要本人明确授权，授权有效5分钟，不能代替取消或恢复确认。成功工具结果保存 subscription_analysis_snapshot，客户答复由本轮有类型成功结果确定性生成后写入 Message，不直接发布模型自由文本；页面／对话从结构化字段展示费用、状态和续费安排。

Plan 可将其快照作为订阅月成本条件的可信源，后续取消／恢复是独立 Workflow，仍须相应确认及强验证。页面 `/subscriptions` 由 Domain API 读取同一业务服务，页面读取不必调用 Agent。

## 边界与失败处理

没有 `subscription.cancel`、`subscription.resume` 或状态对账权限；即使用户在分析中要求直接操作，也不能越过路由和 Workflow。续费提醒不证明发生扣费；没有实际记录显示“暂无扣费记录”，过期预计日期显示“待确认”。

检测只能说明周期交易及合同事实，不判断用户是否实际使用服务。商户不可管理时明确引导到商户，不能声称取消成功。查询失败时保留错误，不凭旧消息补造费用或状态；消息和历史分析是当时快照，新状态需重新查询。

## 源码与验证

[定义](../../../apps/api/src/banking_api/agents/subscription_analysis_agent.py)、[工具](../../../apps/api/src/banking_api/tools/subscriptions.py)、[周期检测](../../../apps/api/src/banking_api/subscriptions/detector.py)、[TaskRunner](../../../apps/api/src/banking_api/runtime/task_runner.py)。

验证覆盖标准绑定、R1 白名单、类型化订阅结果、无记录／过期日期、取消与恢复路由及合同并发。具体用法见 [订阅与消息](../../guides/subscriptions.md)，检查命令见 [测试](../../development/testing.md)。
