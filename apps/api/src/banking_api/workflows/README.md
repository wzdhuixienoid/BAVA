# 确定性业务 Workflows

Workflow 负责有明确状态转换的业务办理，独立于模型工具循环。当前包括即时／预约转账准备、订阅取消／恢复、理财申购／赎回；AA 参与者付款复用转账链路。

补全 → 校验与风险 → 核对确认 → 所需强验证 → 创建／复用 Operation → 提交与恢复。READY_FOR_REVIEW 是草稿校验结果；READY_FOR_COMMIT 也不代表资金成功，执行时须复核授权、租约、安全锁、余额和幂等。

提交工具为 R4_FINANCIAL_COMMIT；转账及理财对账为 R3_FINANCIAL_RECONCILE，side_effect=true，可推进结算，仅对应 Workflow 调用。纯订阅状态查询仍为 R1。Operation 工具只接受 operation_id，从持久资源加载授权 payload 和幂等身份，不接收模型生成的付款参数。

SUBMITTED／UNKNOWN 继续原操作；Provider 明确终态才能收敛 Workflow。理财受理只占用资金／份额，SETTLED 才表示最终结算；普通资源 GET 不推进状态。修改草稿或绑定日期／条款时重新授权，不能复用旧确认。

完整业务清单与状态边界见 [Workflow 架构](../../../../../docs/architecture/workflows.md)。参见 [系统架构](../../../../../docs/architecture/system.md)、[工具权限](../../../../../docs/architecture/tools.md) 和 [安全边界](../../../../../docs/architecture/security.md)。
