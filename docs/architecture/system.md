# 系统架构

本页描述 v0.10.3 的实现。长期设计约束见 [设计原则](design-principles.md)。

## 执行概念

| 概念 | 职责 | 当前实现 |
| --- | --- | --- |
| Agent | 选择下一步只读查询并解释结果 | MinimalBanking、FinancialAnalysis、SubscriptionAnalysis |
| Skill | 稳定组织专业结果 | 消费报告、异常分析说明；消费可信快照 |
| Workflow | 按明确状态推进业务 | 转账、取消订阅、恢复续费授权 |
| Tool | 提供受权限控制的具体能力 | 账户、收款人、金融汇总、订阅分析与受控提交 |
| Plan | 组合已有高层能力 | 固定持久化 DAG、确定性条件与等待用户步骤 |
| Domain API | 向前端提供资源和业务动作 | 报告、订阅、收款人、预约、AA、消息与审计 |

三类 Agent 均为只读。`RequestRouter` 选择执行路径；单个 Agent 或 Workflow 能完成的请求走原路径，跨能力请求才进入 `ConstrainedPlanner` 和 `PlanValidator`。Planner 不能直接提交金融操作。

## 从消息到执行

消息接口将 Message、Task、Event 与 Outbox 意图持久化后返回。Task worker 领取任务，路由至 Agent、Workflow、AA 或 Plan。产品 Agent runtime 使用 LangGraph，负责受步数和工具调用预算约束的工具循环与 checkpoint；Manual runtime 保留为参考。

消费 Agent 通过确定性工具得到金融快照。报告 Skill 组织报告核心和说明，校验后保存 Report Artifact。异常分析 Skill 组织规则证据与中文明细。账户和金融结果通过 typed result 提供给前端，模型文本承担解释。

业务 Workflow 完成意图补全、校验与风险评估，等待用户确认及所需强验证；提交边界复核后创建或复用 Operation，调用 Mock Provider。结果未知时继续查询原 Operation。页面直接取消订阅走受控 Domain API，保留归属、确认、版本、安全锁与幂等检查，未加入 Agent 写工具权限。

AA 请求、分摊和参与者身份由 AAService 管理；参与者付款复用 Transfer Workflow。预约将短期确认转换为内容和时间范围固定的持久授权，ScheduleWorker 到时进入既有 OperationService。

## 后台执行

| Worker | 工作 | 持久化保证 |
| --- | --- | --- |
| TaskExecutionWorker | 领取和执行 Task | PostgreSQL claim、lease、heartbeat、attempt fencing |
| OperationRecoveryWorker | 查询或重试未收敛操作 | 原 Operation、领取租约、退避与终态 |
| OutboxPublisher | 将持久事件发布到 EventBus/SSE | Event 与 Outbox 同事务，领取和重试 |
| ScheduleWorker | 领取到期预约 | 唯一期次、一次性授权、租约及提交复核；仅显式启用时运行 |
| SubscriptionNotificationWorker | 续费提醒、观察扣费、可选模拟扣费 | 用户锁、持久扫描游标、账期与事件去重 |

Worker 由 API 进程托管，不是通用队列平台。EventBus 为进程内广播，跨 API 进程 SSE 尚无实时代理或回放。

## 数据职责

- 合成 JSON fixture 提供账户、交易、收款人和合同基线。有效账户余额结合持久化 Mock Provider 账本读取，运行中的成功扣款不改写 fixture。
- Alembic 管理应用表：对话、任务、计划、授权、业务操作、报告、事件、消息、订阅状态与模拟账本等。
- LangGraph PostgreSQL checkpointer 保存 Agent runtime 进度；它不替代 Task ownership、Workflow 状态、Operation 或授权证据。
- Report 与历史 Task 保留生成或查询时的快照。报告删除与恢复改变可见性，不重算报告核心。
- Dashboard 与审计是受用户范围约束的只读 projection。多服务读取不提供全局原子快照。

## 源码阅读入口

以下路径均相对仓库根目录。

| 模块 | 入口 |
| --- | --- |
| 应用装配与 Worker 生命周期 | [main.py](../../apps/api/src/banking_api/main.py) |
| 路由 | [request_router.py](../../apps/api/src/banking_api/routing/request_router.py) |
| Agent 定义 | [agents](../../apps/api/src/banking_api/agents/README.md) |
| Agent runtime | [LangGraph graph](../../apps/api/src/banking_api/runtime/langgraph/graph.py) |
| Task 执行 | [task_runner.py](../../apps/api/src/banking_api/runtime/task_runner.py) |
| 转账状态机 | [transfer/engine.py](../../apps/api/src/banking_api/workflows/transfer/engine.py) |
| 提交与恢复 | [operation_service.py](../../apps/api/src/banking_api/application/operation_service.py) |
| 计划验证 | [validator.py](../../apps/api/src/banking_api/planning/validator.py) |
| 前端工作台 | [page.tsx](../../apps/web/app/page.tsx) |

完整 HTTP 契约通过运行环境的 `/docs` 查看；客户端类型位于 `packages/api-client`，使用 `pnpm api:generate` 更新。
