# 安全与事实边界

## 身份与归属

development 身份必须显式配置。OIDC 模式验证 JWT 签名、issuer、audience、有效期及允许算法，再将 `(issuer, subject)` 映射为内部 Principal；不按邮箱或姓名自动继承合成数据。生产拒绝 development 模式，合法外部身份仍须显式 provision。

资源与工具按 Principal.user_id 限定，跨用户资源返回 404。浏览器参数、模型生成的 user_id、Skill 或知识文本不能改变执行身份。HTTP credential 不进入 Message、Task、Event、Prompt 或 checkpoint；Task worker 从持久用户归属重建服务端身份。

三个业务 Agent 均为只读。ToolRegistry、ToolExecutor 与 PolicyService 检查 caller 和白名单；运行时不能冒充 Workflow。写入及可推进结算的对账工具只允许对应工作流，Recovery 只处理已有操作。清单见 [Tools](tools.md)。

## 确认、强验证与授权

| 操作 | 控制 |
| --- | --- |
| 账户、账单、消费、订阅查询 | GREEN，自动执行 |
| 取消可管理订阅 | YELLOW，明确确认 |
| 保存收款人 | 页面核对并确认 |
| 所有即时转账、预约与周期授权 | RED，确认 + Mock 强验证 |
| 所有理财申购及赎回 | 确认 + Mock 强验证，绑定具体数量、条款、日期及所需测评证据 |
| 恢复订阅续费授权 | RED，确认 + Mock 强验证；本次不立即扣费 |

Tool 权限风险、业务控制等级及理财产品风险是独立类型。转账仅 CNY，其他币种拒绝；没有小额免验证规则。默认 Approval 600 秒、强验证 300 秒。字段或绑定版本改变会使旧授权失效。

确认绑定 canonical payload hash。八个 Operation 工具重新核对本人、业务类型、已消费且绑定该 Operation 的 Approval、Workflow 及实际 payload 摘要。恢复沿用原持久授权，不以过期 TTL 重开交易；新提交仍执行身份、安全锁、幂等及业务校验。

预约／周期使用内容、期次和执行窗口固定的独立持久授权，不延长全局 TTL，不允许改作即时转账。AA 发布不授权参与者付款，每人只能授权自己的份额。已授权订阅后续账期由合同与扣费账本控制。

页面取消订阅还检查合同版本、幂等键、用户归属、可取消性与安全写锁；取消与扣费通过锁和合同状态协调。该接口不向 Agent 暴露直接取消能力。

## 风控、余额与恢复

转账日累计按用户及 Asia/Shanghai 自然日计算，包含成功和执行中 exposure，同一 Operation 不重复计入。提交重新评估，模型不决定风险或可用余额。账户锁串行化转账、订阅及理财对共享余额的决策；账本和业务状态原子保存必要事实。

Security Guard 默认在 10 分钟内 3 次强验证失败，或 5 分钟内 5 次绕过控制尝试后，锁定新写操作 15 分钟。没有管理员手工解锁页面。只读查询和已受理操作恢复继续允许，消费异常提醒不自动触发此锁。

UNKNOWN 表示结果未确认，保留原 Operation、占用和最后阶段；不得另建扣款。Task 完成、确认通过、预约创建、AA 发布和订单受理均不代表最终资金成功。

## 理财与证据

未测评可看目录和客观比较，个性化推荐与新申购要求本人有效且适合的测评。风险下降或测评失效不阻止已有持仓赎回。测评只给风险上限，本次保本、亏损意愿和流动性是额外条件；不能为凑数放宽。

产品资料按产品版本、有效时间、正文 hash、结构化条款及来源校验，冲突停止新申购。受理后使用原条款结算。模拟 DESIGN 画像不是银行披露、实际持仓或收益预测，不覆盖净值及历史条款。通用教育资料不能证明产品资格或目标组合。

WealthAdvisor 只读 allowlist 不开放任意网络、SQL 或写工具。模型正文校验事实／证据作用域、版本、候选、关键数字、比较关系、资格及禁止承诺；最多修复一次，再确定性降级。有限校验不是自然语言的完整事实证明。知识内容不能改变技能、工具、排序或授权。

推荐／购买入口键只用于创建幂等，不是金融授权。口头声称完成测评须重新查询本人记录。元和份严格区分，全部赎回绑定后端明确份额，提交不能静默扩大或缩小。关闭新业务后，已受理订单与 UNKNOWN 原操作仍继续恢复，不能释放占用或视为撤单。

## 快照、删除与审计

理财上下文读取同时检查 user_id、conversation_id、已完成任务类型和来源；精简快照不携带完整账户明细、凭据或验证信息。个人银行续页只继承本人本对话可信条件。旧推荐不是当前资格或授权，新对话不继承旧意愿。

对话、报告、预约、AA 请求及通知的删除分别改变允许的可见性，不删除金融账本或撤销交易。已受理理财对话只有关联订单、Operation 和 Workflow 证据完整才可绕过相应删除阻断；无受理证据的未知状态、其他活动任务和草稿不豁免。AA 删除仅限本人发起、其他份额全部取消且无付款提交的请求。

`GET /api/v1/tasks/{task_id}/audit` 投影持久事件、风险、授权 hash、用户动作、Condition 与 Provider 关联。事件是历史证据，资源详情是当前状态；不以最后成功覆盖中间未知，缺失证据不补造，超过上限提示不完整。

审计不展示隐藏推理、完整 Prompt、JWT、API key 或验证码。提供商 reasoning_content 仅作模型协议续接。应用 append-only Event 不等于数据库防篡改保证。外部来源只接受经白名单校验的 http／https，不接受 javascript／data URL。

## 当前范围

真实银行、真实 MFA、真实 IdP 完整验收、独立 Worker 部署、跨进程 SSE broker、事件回放及完整生产监控尚未完成。开发 reset 是明确按用户的数据清理，不能替代业务撤销。

源码入口：[认证](../../apps/api/src/banking_api/security/authentication/service.py)、[Policy](../../apps/api/src/banking_api/policy/service.py)、[Security Guard](../../apps/api/src/banking_api/security/guard.py)、[审计](../../apps/api/src/banking_api/audit/README.md)。配置见 [环境说明](../development/setup.md)，操作排查见 [运行维护](../development/operations.md)。
