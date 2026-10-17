# 对话上下文范围

此目录没有独立 Memory 服务或运行实现。当前上下文由 runtime ContextBuilder、持久 Message／Task、个人银行查询条件和 wealth/context.py 提供。

账单“下一页”复用本人本对话最近完成查询的筛选与 as_of。理财追问使用经过 user_id、conversation_id 和任务类型校验的精简分析快照；新对话不继承预算或候选。本人测评属于账户资料，不能作为新的交易授权。

没有长期向量记忆、跨用户记忆或自动用户画像写入。具体事实与恢复边界见 [系统架构](../../../../../docs/architecture/system.md) 和 [个人银行](../../../../../docs/architecture/agents/personal-banking.md)。
