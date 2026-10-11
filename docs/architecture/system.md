# 系统架构

本页描述 v0.11.2 的实现。长期设计约束见 [设计原则](design-principles.md)。

## 执行概念

| 概念 | 职责 | 当前实现 |
| --- | --- | --- |
| Agent | 选择下一步只读查询并解释结果 | MinimalBanking、FinancialAnalysis、SubscriptionAnalysis、WealthAdvisor |
| Skill | 稳定组织专业结果 | 消费报告、异常分析说明；消费可信快照 |
| Workflow | 按明确状态推进业务 | 转账、取消订阅、恢复续费授权、理财申购/赎回 |
| Tool | 提供受权限控制的具体能力 | 账户、收款人、金融汇总、订阅分析与受控提交 |
| Plan | 组合已有高层能力 | 固定持久化 DAG、确定性条件与等待用户步骤 |
| Domain API | 向前端提供资源和业务动作 | 报告、订阅、收款人、预约、AA、消息与审计 |

四类 Agent 均为只读。`RequestRouter` 选择执行路径；单个 Agent 或 Workflow 能完成的请求走原路径，跨能力请求才进入 `ConstrainedPlanner` 和 `PlanValidator`。Planner 不能直接提交金融操作。

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

## 理财边界

`wealth/` 保存结构化目录、净值、测评、订单、持仓、占用和账本。`knowledge/wealth.py` 提供可替换关键词检索接口，无Embedding或新向量库。资料版本先过滤再检索；资料内容永远不能授予工具权限。产品风险类型与Tool权限RiskLevel分离，交易规则与推荐排序由确定性服务计算。

余额服务复用旧advisory key，所有账户写路径共享可用余额。理财锁顺序为Security用户锁 → Workflow → 账户 → 持仓 → 订单/占用，调用Provider前结束应用快照事务。受理与结算各为短事务；不持锁等待模型或网络。申购成交与结算同事务，赎回成交和到账分阶段；独立账本不进入消费fixture。

复用Approval、Reauthentication、Operation、Event/Outbox、消息、审计和OperationRecoveryWorker。正常等待直接设置下一业务阶段，不增加故障次数；未知结果退避查询原操作，保持占用和最后订单阶段。只有SETTLED才投影资金成功。页面创建交易同时保存本人Conversation、Message、Task和唯一source_task_id，刷新可恢复。

不可变产品版本内保存关联资料hash清单；当前资料的正文hash、结构化条款、资料版本及可访问来源必须一致，否则停止新申购。检索也过滤hash不匹配资料，不把被改动的文本作为有效证据。已受理订单结算仍使用原订单条款快照。

新业务开关与执行能力注册分开。development/test始终注册理财只读和受控Operation查询/提交工具；关闭开关只阻止新的测评、草稿、授权和首次受理，已有订单幂等重放及恢复继续按原快照结算。production不注册Mock工具，Provider也校验执行环境。`GET /api/v1/wealth/status`返回开关及目录/问卷版本；页面静态资料按版本加载，动态资源统一刷新、禁止重叠并在隐藏时暂停。

自然语言数量保留元/份单位并严格校验方向，歧义进入补全草稿；全部赎回在后端唯一确定持仓并绑定明确可用份额，提交不静默缩减数量。推荐通过共用的结构化需求约束解析器识别保本、否定偏好和流动性硬约束，HTTP和Agent使用同一服务与用户测评标记。订单说明投影由后端统一提供错误码、中文原因、下一步、最后阶段和预计处理时间。

## v0.11.2 理财顾问分析

WealthAdvisoryService 共用需求整理、确定性筛选、Decimal 费用情景、完整到账链路、统一历史窗口和证据。新增 POST /api/v1/wealth/analysis；原 compare 列表接口兼容，HTTP 与 Agent 都传本人 user_id 计算权限。

LangGraph 对话先生成并保存 typed 最终分析，以 wealth_analysis 作为唯一展示来源。模型仅组织批准的段落，失败提供具体差异的确定性降级。Task.output 快照保存需求、顺序、资料/测评版本和参考时间；ContextBuilder 与 Router 使用 owner/conversation 校验后的精简快照进行追问路由，不依赖最近十条文本或进程字典。

共享 WealthAnalysisCard 用于理财中心和对话，正文先于卡片，来源区分产品与教育资料；静态数据、动态轮询与金融工作流维持 v0.11.1 的分工。本轮无数据库迁移，不改写历史条款、金融账本或旧消息。


理财对话复用WealthProductCard，理由、限制及费用/时间情景放在卡片外的正文。WealthEvidencePanel独立于分析容器，共用资料交互。持久订单受理事实投影到Workflow展示DTO，对话“申请已提交”与异步金融完成分离；成交/到账消息展示实际结果，Worker及账本状态机不变。

`skill:wealth-recommendation` 将校验后的WealthAnalysis转换为客户呈现DTO，保留原事实、
证据与后台需求字段，隔离展示文案和金融决策。对话软删除保留独立已受理理财链路；
订单投影标记conversation_deleted，理财中心移除无效对话入口但保留审计和恢复状态。
