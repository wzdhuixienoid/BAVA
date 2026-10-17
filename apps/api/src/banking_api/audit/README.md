# 审计投影

AuditProjection 从本人 Task、持久 Event 及关联 Plan／Workflow／Approval／Reauthentication／Operation／Provider 资源构建 AuditTrace，由任务 audit API 提供给页面。

时间线展示已记录决定，资源详情是当前快照；保留中间未知和失败，不补造旧事件。事件或资源超过展示上限时标记不完整。safe_text 与允许字段投影限制输出，不复制完整消息、工具原文、Prompt、隐藏推理或凭据。

应用事件追加和本模块投影不构成数据库防篡改平台，也不提供真实银行独立审计认证。状态和安全边界见 [安全说明](../../../../../docs/architecture/security.md)。
