# Tool 使用与审计（应用版本 0.11.3）

审计日期：2026-10-15。范围是应用登记的 function tools、模型协议、运行时、工作流、后台恢复以及银行数据投影。这里的 Tool 是应用能力，不是 MCP 服务；Python 文件名不需要与 MCP 工具约定混用。

## 实际使用位置

`main.create_app()` 在 development/test 环境登记 27 个工具，production 环境登记其中 16 个（11 个模拟理财工具不登记）。三个 Agent 通过 `ContextBuilder → OpenAICompatibleProvider → ManualAgentRuntime/LangGraphAgentRuntime → ToolExecutor → PolicyService` 调用允许的只读能力。金融分析和理财对话由 TaskRunner 强制使用 LangGraph；Manual 是账户等基础交互的参考运行时。运行时验证标准 Skill 绑定，Skill 指令不能扩大工具权限。

| 使用方 | 工具能力 |
| --- | --- |
| PersonalBankingAgent | ACCOUNT：账户、余额、账单与收款人；SPENDING：消费分析；COMBINED：两类所需能力。未明确要求异常时不开放完整异常工具 |
| SubscriptionAnalysisAgent | 订阅成本和续费分析 |
| WealthAdvisorAgent | 产品目录、单品、对比、推荐、资料检索、本人持仓和订单 |
| TransferWorkflowEngine | 账户、余额、收款人，已授权转账提交及对账 |
| SubscriptionCancellationWorkflow | 订阅分析、已授权取消/恢复及状态查询 |
| WealthExecutionEngine | 已授权申购/赎回提交与后续成交、到账对账 |
| OperationRecoveryWorker / 预约和 AA 执行 | 通过上述工作流引擎恢复同一个 Operation；沿用持久授权、幂等键和租约，不给模型开放写工具 |

HTTP 页面读取由业务服务提供，金融写入经 Workflow/Operation。订阅定时扣费 Worker 调用已授权周期合同对应的 Mock 银行服务，不是一次模型 function call；它的合同授权、失败不扣款和周期幂等另有测试。数据库查询、内部计算函数也不应全部注册为模型工具。

## 完整登记清单

19 个纯读取、5 个提交、3 个会推进结算的对账工具。能力 ID 用于内部权限；函数名用于模型协议，两者有意分开。

| 能力 ID | 函数名 | 分类 |
| --- | --- | --- |
| account.list | list_accounts | R1 读取 |
| account.get_balance | get_balance | R1 读取 |
| account.statement | get_account_statement | R1 读取 |
| payee.search | search_payees | R1 读取 |
| payee.list | list_payees | R1 读取 |
| transaction.spending_summary | get_spending_summary | R1 读取 |
| transaction.category_breakdown | get_category_breakdown | R1 读取 |
| transaction.compare_periods | compare_spending_periods | R1 读取 |
| transaction.top_transactions | get_top_transactions | R1 读取 |
| transaction.detect_anomalies | detect_transaction_anomalies | R1 读取 |
| subscription.analyze | analyze_subscriptions | R1 读取 |
| subscription.get_status | get_subscription_cancellation_status | R1 读取 |
| subscription.cancel | cancel_subscription | R4 提交 |
| subscription.resume | resume_subscription | R4 提交 |
| transfer.commit | commit_transfer | R4 提交 |
| transfer.get_status | get_transfer_status | R3 对账，可能入账 |
| wealth.list_products | wealth_list_products | R1 读取 |
| wealth.get_product | wealth_get_product | R1 读取 |
| wealth.compare_products | wealth_compare_products | R1 读取 |
| wealth.recommend | wealth_recommend | R1 读取 |
| wealth.search_knowledge | wealth_search_knowledge | R1 读取 |
| wealth.list_positions | wealth_list_positions | R1 读取 |
| wealth.get_orders | wealth_get_orders | R1 读取 |
| wealth.purchase.submit | wealth_purchase_submit | R4 提交 |
| wealth.redeem.submit | wealth_redeem_submit | R4 提交 |
| wealth.purchase.status | wealth_purchase_status | R3 对账，可能成交/入账 |
| wealth.redeem.status | wealth_redeem_status | R3 对账，可能成交/到账 |

`tools/banking/` 提供账户、交易与转账；`tools/subscriptions.py` 提供四个订阅工具；`wealth/tools.py` 提供十一个模拟理财工具。登记、调用与授权分别由 `registries/tool_registry.py`、`tools/executor.py`、`policy/service.py` 维护。

## 标准与执行契约

协议按 [OpenAI Function calling](https://developers.openai.com/api/docs/guides/function-calling) 和 [Chat Completions](https://developers.openai.com/api/reference/resources/chat/subresources/completions/methods/create) 核对：工具声明为 `type=function`，函数名只含字母、数字、下划线或连字符且不超过 64 字符；参数是 JSON Schema 对象；工具结果与原 `tool_call_id` 对应，保留模型所需的推理续接字段。

本项目继续使用兼容 Chat Completions 的默认非 strict 模式，并在服务端用 Pydantic 校验。没有声称提供模型侧 strict 保证。可选/默认字段、Schema `$defs` 和确定性业务校验不能直接照搬为所有服务商都支持的 strict 子集；未设置 `strict:true` 本身不是当前协议违规。输出 Schema 使用 serialization 模式，覆盖实际返回的计算字段。以后启用 strict 时须先转换 Schema、确认服务商支持并验证兼容性。

- ToolSpec 必须有具体输入/输出模型、明确 caller、非空描述及支持的风险分类。全部输入拒绝未知字段，输出为结构化对象；拒绝重复能力或函数名。不可在登记后修改工具的权限或 handler，`model_copy` 也必须在登记时重验。
- 执行前检查认证主体、caller、Agent 白名单及风险；用户文本、工具结果、Skill 和模型生成的 user_id 均不能授予权限。Agent 运行时不能冒充 workflow caller。
- 输入错误为可修复结构化错误，执行异常或输出契约失败为明确错误；不把任意 Provider 字符串、空结果或成功/查询状态混用当成成功。
- R3/R4 只允许对应工作流。八个 Operation 工具均重新核对本人、业务类型、已消费且绑定该 Operation 的 Approval、workflow 和 payload hash，并重算实际 payload 摘要。已消费的授权在恢复时不重新检查原确认 TTL，避免已受理交易被错误阻断；新提交的身份验证、租约、安全锁和幂等校验仍由业务执行层处理。

## 本轮发现与修复

| 原问题 | 修复与实际影响 |
| --- | --- |
| 转账、申购和赎回状态工具标为只读，实际可能完成入账 | 新增 R3_FINANCIAL_RECONCILE，有副作用、仅对应工作流可调用；普通持仓/订单查询仍纯读取 |
| 只凭本人 Operation ID 读取并提交，未统一验证业务类型和持久授权 | 八个操作工具共用 `authorized_operation`；跨业务、跨用户、未消费授权、授权绑定或 payload 被改都会在 Provider 前拒绝 |
| 工具登记缺契约校验，登记后可修改权限 | 冻结 ToolSpec，登记时重验名称、具体模型、Schema、caller 和风险/副作用一致性 |
| 理财金额校验抛出业务异常时可能直接中断循环 | 转为可修复参数错误，不调用 handler；模型有机会修正参数 |
| 预构造 Pydantic 对象、无效 Provider 状态或序列化异常可绕过/逃出结果校验 | 输入输出对象重新展开校验；输出序列化纳入错误边界；提交 outcome 与查询 status 限定枚举且只能二选一 |
| Manual 丢失推理续接，原始坏 JSON 被二次编码，调用 ID 可重复 | 两个运行时保留续接与 ID 对应；坏 JSON 原样供修复；拒绝同轮重复 ID 和不合法函数名 |
| Manual 忽略请求选择的 Agent，caller 可冒充其他执行方 | 实际 Agent 决定上下文和白名单；caller 不匹配在模型/工具执行前拒绝 |
| 消费类工具和总览只读静态 fixture，漏掉刚成功的订阅续费 | 五个消费工具和总览使用同一已入账投影；仅成功扣费计入消费，提醒/失败/待成交不计；理财现金变动列入账单并从日常消费/收入分析排除 |
| 18 项数据库测试缺 postgres 标记，专项未选中 | 补齐标记，71 项 PostgreSQL 测试实际运行通过 |
| 理财工具描述仅有英文函数后缀，模型难以区分用途 | 增补每个查询的业务目的、参数作用和事实边界 |

共享已入账投影仍支持账户归属、北京时间筛选和余额一致性。该原型无真实银行接入，不能把这些 Mock 和有限模型检查当作真实资金渠道认证。

## 验证

回归文件：`test_tool_contract_audit.py`、`test_tool_executor.py`、`test_runtime_parity.py`、`test_security_adversarial.py`、`test_transfer_operations.py`、`test_account_statement.py` 及 PostgreSQL 并发/恢复套件。`test_release_version.py` 校验 Python、FastAPI OpenAPI、三个 package.json、uv.lock 和当前文档标题，并确保网页版本来自 web/package.json。

本轮验证结果见 [更新说明](../releases/release-notes-v0.11.3.md)。历史审计证据保留于 v0.11.2 更新说明。无新增数据库迁移，head 仍为 0034。
