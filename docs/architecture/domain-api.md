# Domain API：资源与受控业务动作

## 职责与契约

Domain API 为 Web 提供资源查询、历史快照和明确用户动作。路由通过 Principal 和应用服务访问业务状态，页面不必先调用 Agent；模型 function Tool 也不等于 HTTP 路由。POST 可能是只读分析，也可能是金融动作，须按实际语义判断副作用。

业务路由统一在 `/api/v1` 下，参数与 DTO 以运行中的 `/openapi.json`、`/docs` 为准。`/health` 在前缀外，只表示进程响应。TypeScript 类型由 packages/api-client 从当前 OpenAPI 生成；页面通过统一已认证客户端请求。

## 当前资源分组

下表路径相对 `/api/v1`，涵盖当前 api/router.py 登记的业务路由；完整字段不在文档手工复制。

| 路由模块／路径 | 资源与动作 | 关键边界 |
| --- | --- | --- |
| conversations：`/conversations` | 创建、读取、命名、删除；提交消息 | Message／Task／Event／Outbox 持久化，删除不撤单 |
| tasks：`/tasks` | 任务、事件及审计链 | 类型化结果、历史决定和当前状态分开 |
| events：`/events` | 认证 SSE | 进程内广播，无跨进程 broker／事件重放保证 |
| dashboard：`/dashboard`、`/dashboard/transactions` | 账户、消费与异常；已入账账单筛选／分页 | 与对话共用 AccountStatementService，读取不推进结算 |
| reports：`/reports` | 历史报告、详情、删除／恢复 | 保存原快照，不因刷新重算 |
| workflows：`/workflows` | 业务状态、补全、核对、确认、验证及提交 | 通过 WorkflowService 和确定性引擎，不绕授权 |
| operations：`/operations` | 只读详情；显式 actions/reconcile | 对账可推进原操作，仅本人、版本／租约检查 |
| subscriptions：`/subscriptions` | 订阅分析、单项及页面确认取消 | 确认、合同版本、幂等和安全锁 |
| payees：`/payees` | 收款人列表、添加、修改、删除 | 本人范围，明确核对，历史流水证据保留 |
| schedules：`/scheduled-transfers` | 预约／周期列表与管理动作 | 未提交才可取消；已授权到期仍受提交校验 |
| aa：`/aa-requests`、`/aa-shares`、`/aa-accounts` | AA 请求、份额及本人付款账户 | 发布不扣款，每人独立授权；完全取消请求可按规则软删除 |
| notifications：`/notifications` | 列表、证据详情、已读、删除 | 本人归属，删除不删账本，同源稳定去重 |
| plans：`/plans` | 计划、接管、恢复、只读回退 | 静态能力和单写边界不变 |
| wealth：`/wealth` | 目录、知识、分析、测评、持仓、订单、交易草稿／动作 | 非生产 Mock 路由；新业务开关与既有订单恢复分离 |
| security：`/security` | 安全状态、个人免密额度、认证器绑定、订阅读取确认和独立审计 | 额度修改须强验证和版本校验，上限200元；认证器保密、一次性动态码；全部按本人隔离，没有管理员手工解锁 API |
| demo：`/demo/readiness` | 本地专用演示初始状态 | 非生产、合成数据；不是普通健康检查或真实银行 API |

AA 模块还提供 `/mock-sessions` 供显式开发配置下的隔离多身份测试；不在 AA 页面提供身份切换，不作为生产认证。真实身份认证边界见 [安全](security.md)。

## 写入、归属与一致性

浏览器只能请求本人资源；user_id 由认证 Principal 决定，跨用户资源按路由策略拒绝。写 API 在服务端校验明确确认、版本、幂等及相应安全控制；需要资金授权时进入 Workflow／Operation，不能仅信任按钮状态或客户端计算。

理财页面创建草稿时把 Conversation、Message、Task 与幂等创建键一起保存，避免空对话及重复草稿。页面取消订阅、收款人编辑、AA 发布／关闭等非 Agent 动作也保留服务端状态检查，不意味着给 Agent 写权限。

资源 GET、已保存报告和普通持仓／订单查询不推进结算；显式 reconcile 及后台恢复可能推进资金阶段。Task 终态、受理、消息提醒与实际入账分别展示。HTTP 版本冲突应刷新核对，不能自动重提资金业务；多资源 GET 不构成全局原子快照。

## 通知、前端与验证

Web 从业务资源读取最终事实，SSE 提供增量事件，恢复仍依赖资源 API。通知保存持久来源和证据，已读／删除只改变可见性，不影响业务执行。页面隐藏暂停相关轮询，恢复可见重新读取，不靠模型解释修正余额。

源码：[总路由](../../apps/api/src/banking_api/api/router.py)、[依赖与 Principal](../../apps/api/src/banking_api/api/dependencies.py)、[路由目录](../../apps/api/src/banking_api/api/routes)、[应用服务](../../apps/api/src/banking_api/application)、[Web 客户端](../../apps/web/lib/api/client.ts)。

验证覆盖 OpenAPI／客户端类型、归属、输入错误、版本冲突、幂等、资源状态和 UI 交互。路由分组与实际注册的覆盖检查防止漏写新资源；命令见 [测试](../development/testing.md)，运行边界见 [系统架构](system.md)。
