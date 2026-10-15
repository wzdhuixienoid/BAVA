# 受权限控制的工具

应用当前版本：0.11.2。26 个工具的使用位置、完整清单、协议、权限及验证见 [Tool 使用与审计](../../../../../docs/architecture/tools.md)。

新增工具须提供具体 Pydantic 输入/输出、用途描述、能力 ID、合法函数名、风险/副作用和 caller；由 ToolRegistry 重验登记，经 ToolExecutor/PolicyService 执行。金融提交与对账仅向对应 Workflow 开放，不能通过扩大 Agent 白名单授权。Operation 工具还须验证 operation_authority；Provider 和工作流继续负责幂等、安全锁和执行租约。纯读取与会推进状态的对账必须分开标记。
