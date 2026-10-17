# Tools：契约与权限

本文说明应用登记的 function tools、模型协议、运行时、工作流、后台恢复以及银行数据投影。这里的 Tool 是应用能力，不是 MCP 服务；Python 文件名不需要与 MCP 工具约定混用。

## 实际使用位置

`main.create_app()` 在 development/test 环境登记 27 个工具和三个 Agent；production 登记其中 16 个工具和两个 Agent，不登记 Mock 理财能力。Agent 通过 `ContextBuilder → OpenAICompatibleProvider → ManualAgentRuntime/LangGraphAgentRuntime → ToolExecutor → PolicyService` 调用允许的只读能力。金融分析和理财对话由 TaskRunner 强制使用 LangGraph；Manual 是账户等基础交互的参考运行时。运行时验证标准 Skill 绑定，Skill 指令不能扩大工具权限。

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

## 已入账投影

消费工具和总览使用同一已入账投影，仅成功订阅扣费计入消费。理财现金变动列入账单，但不计入日常消费／收入；提醒、失败、占用和待成交不是实际扣款。

共享已入账投影仍支持账户归属、北京时间筛选和余额一致性。该原型无真实银行接入，不能把这些 Mock 和有限模型检查当作真实资金渠道认证。

## 验证

回归文件：`test_tool_contract_audit.py`、`test_tool_executor.py`、`test_runtime_parity.py`、`test_security_adversarial.py`、`test_transfer_operations.py`、`test_account_statement.py` 及 PostgreSQL 并发/恢复套件。`test_release_version.py` 校验 Python、FastAPI OpenAPI、三个 package.json、uv.lock 和当前文档版本与导航，并确保网页版本来自 web/package.json。

检查命令见 [测试与演示](../development/testing.md)。
