# 安全与事实边界

## 身份与权限

开发模式显式指定固定用户。OIDC 模式验证 JWT 签名、issuer、audience、有效期与允许算法，将 `(issuer, subject)` 映射至内部 Principal。外部身份必须 provision，不按邮箱或姓名自动继承模拟数据。生产环境拒绝 development 身份模式。

资源与工具查询按 Principal.user_id 限定；跨用户资源访问表现为 404。模型参数和浏览器请求不能切换 authority。HTTP credential 不进入 Message、Task、Event、Prompt 或 checkpoint；Task worker 从持久化用户归属重建服务端执行身份。

ToolRegistry 与 PolicyService 限定调用者能力。四个 Agent 都只读；写 Tool 由确定性 Workflow 调用，接受持久化 operation_id。Recovery 只能处理既有操作，不扩大调用权限。

## 用户控制

| 操作 | 风险与控制 |
| --- | --- |
| 账户、消费、订阅查询 | GREEN，自动执行 |
| 取消可管理订阅 | YELLOW，明确确认 |
| 保存收款人 | 页面核对并明确确认 |
| 所有理财申购及赎回 | 确认 + Mock强验证，绑定具体交易日、条款和测评证据 |
| 所有即时转账、预约与周期授权 | RED，确认 + Mock 强验证 |
| 恢复订阅续费授权 | RED，确认 + Mock 强验证；本次不立即扣费 |

静态工具权限与业务风险等级彼此独立。当前转账仅 CNY，非 CNY fail closed；旧 1000 元风险阈值不决定当前认证要求。

默认 Approval 600 秒、强验证 300 秒。预约与周期转账通过独立持久授权绑定固定内容、期次和执行窗口，不延长全局 TTL，也不能用于即时转账。已授权订阅未来账期由模拟合同与扣费账本控制。

页面直接取消接口校验确认标记、合同版本、幂等键、用户归属、可取消性和安全写锁；不向 Agent 暴露直接取消能力。取消与自动扣费通过锁和合同状态协调。

## 风控与安全熔断

转账日累计按用户及 Asia/Shanghai 自然日统计，计入成功与执行中 exposure，不重复计算同一 Operation。提交时重新评估，模型不决定风险。

Security Guard 默认为 10 分钟内连续 3 次强验证失败，或 5 分钟内 5 次绕过控制尝试，触发 15 分钟 WRITE_LOCKED。没有管理员手工解锁界面。异常消费提示不自动触发该写锁。

## 结果与审计

Task COMPLETED 只说明处理完成，不能作为资金成功凭据；确认、强验证、预约创建与 AA 发布也不能。业务卡片和回执读取 Workflow、Operation、Provider 的权威状态，UNKNOWN 保持结果确认中。

`GET /api/v1/tasks/{task_id}/audit` 展示持久事件、风险、用户动作、授权 hash、Condition 与 Provider 关联。历史决定和当前状态分别展示，不以最后成功覆盖中间未知结果。缺失历史证据不补造，超出展示上限会提示不完整。

审计不展示隐藏推理、完整 Prompt、JWT、API key 或验证码。应用 append-only Event 不等于数据库防篡改。模型解释没有全面语义验证；Prompt Injection 防护依赖服务端权限与业务边界，不能保证自然语言永远正确。

真实 IdP、真实银行、真实 MFA、独立 Worker 部署、跨进程 SSE broker、事件回放与完整监控仍未完成。演示 reset 只用于显式 development/test 用户，不能替代业务撤销。

源码入口：[认证](../../apps/api/src/banking_api/security/authentication/service.py)、[Policy](../../apps/api/src/banking_api/policy/service.py)、[Security Guard](../../apps/api/src/banking_api/security/guard.py)、[审计](../../apps/api/src/banking_api/audit/README.md)。

理财Agent只允许7项只读工具。申购/赎回提交工具各只接收operation_id并只允许对应Workflowcaller，Provider重新校验持久授权、归属和原快照。条件自动投资和多笔写业务整体拒绝。未测评可查询，但不能个性化推荐或申购；客户风险下降/测评失效不阻止赎回。资料冲突禁止新申购，受理后按原条款结算。后来触发的安全写锁不阻塞已受理订单兑付。

关闭`MOCK_WEALTH_ENABLED`不是撤销受理订单的权限。已受理订单及UNKNOWN原操作继续恢复；新测评、交易草稿、授权和首次受理均拒绝，未受理Operation明确失败且不占用资金/份额。查询保持Principal归属，Agent写权限不变，production继续禁止Mock理财执行。元与份不可互换；全部赎回绑定后端实际份额并在提交时重查，不能借刷新静默扩大或缩小授权。测评只给出风险上限，本次保本/不接受损失和流动性要求是额外硬约束；否定表达不得被关键词命中覆盖。

## v0.11.2 理财分析与证据边界

WealthAdvisor 保持只读 allowlist；知识检索不开放任意网络、SQL 或写工具。推荐/比较快照使用 Task.output，不扩张金融表。读取前校验 user_id、conversation_id、已完成理财任务、来源 Task ID，并限定最近快照数量。精简上下文不携带完整账户明细、密码、token 或 reauth 信息。

模型收到服务已确定的分析块及 fact/evidence ID，只能返回完整、有效且顺序合规的块 ID 列表；这不是对任意自由文本金融结论的正则验证。契约失败最多一次修复，之后降级，不重新运行交易。知识中的指令仅为不可信引用文本，不能修改权限、工具选择、排序或授权。

产品资料必须匹配当前或明确历史版本并通过 hash/条款校验。通用官方知识只用于教育解释。内部资料路径与外部官方 http/https 来源分别校验；拒绝 javascript/data URL。旧推荐快照不是当前购买资格或交易授权；提交继续复核本人账户、产品、测评、金额/份额和有效授权。

申购入口前置校验本人有效且适合的风险测评，即使交易字段尚未补齐也不能跳过。对话不创建无测评购买草稿；页面 API 在创建对话/任务前拒绝，避免空记录。已有订单幂等查询和恢复、已有持仓赎回不受该新建申购限制。

购买意向与写操作分离：未完整指定产品/本人账户/数量的购买消息进入只读选购分析；产品卡点击只打开编辑器，填写后由现有 owner-scoped Workflow API 原子创建核对草稿。分析候选的 purchase_entry_key 仅作防重复创建键，不是授权。客户端展示权限不能替代服务端当前测评与交易校验。“完成测评”必须重新查询本人实际记录，历史意图仅在本人本对话读取，不继承任何 Approval 或 Reauthentication。模型运行不可用时，同一只读事实仍能确定性展示；不能因此新建金融 Operation。


理财受理回复与金融成功分离：仅从本人Workflow关联持久订单的ACCEPTED/CONFIRMED/SETTLED事实只读投影order_received/order_stage。前端结束受理回复动画，不修改Task/Workflow/Operation状态，不产生提前成功回执，不替代原Provider恢复。无受理证据的UNKNOWN不投影为已受理；混合业务依据剩余未完成部分展示处理状态。新增字段默认值兼容历史客户端。

理财已受理对话软删除只允许 owner-scoped 的订单、Operation、COMMITTING Workflow
关联证据均存在时绕过对应 WAITING_EXTERNAL 的删除阻断。未知且无受理订单、未提交
草稿、其他任务及 Plan 不豁免。保留订单/占用/账本/任务和审计，恢复仍执行原金融状态机。
新 recommendation Skill 的 tools=[]；客户呈现 DTO 不扩展顾问权限。

理财目录只读查询不以问卷目标替代本次投资需求；新对话快照仍按user_id与
conversation_id双重限定。已保存风险测评是本人账户资料，不能作为新交易授权。

## v0.11.3 技能和说明边界

只加载可信应用包的Markdown技能，拒绝穿越、绝对路径和越界symlink，不读取个人技能目录。Skill不能扩大allowlist；产品和知识内容只是证据。语义模型提出解释，数量、对象及资格由后端核验。

正文核验事实/证据作用域、版本、候选、关键数字、比较关系、资格和禁止承诺，失败有限修复后降级。这不是任意自然语言的完整事实证明。推荐不是授权；确认、强验证、幂等和恢复规则保留。提供商reasoning_content只用于协议续接，不在用户页面展示，不作为权限或事实依据。

## v0.11.4 模拟设计来源

DESIGN资料是项目编写的虚构产品设计，不是银行披露、实际持仓或交易授权。发布时间之前及历史版本检索不自动加入新画像。画像不改变原条款、合成净值或历史订单；组合比例不得用来预测合成收益。增长目标只影响已通过资格和硬条件的只读候选，不提高本人测评等级，不推断最大可承受亏损。
