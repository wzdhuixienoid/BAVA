# 历史档案：ManualAgentRuntime vs LangGraphAgentRuntime v0.2.2

> 历史材料，保留原记录日期、版本和结论。旧风险规则、待办事项、测试数量与本地部署状态不代表 v0.10.3；当前说明见 [文档导航](../../README.md)。

本文只比较仓库中已实现的代码，不评估 LangGraph 的其他产品功能。两种 Runtime 都通过项目自己的 `AgentRuntime` Protocol 被 `TaskRunner` 调用，并使用相同的 FakeProvider parity suite。

## ManualAgentRuntime

| 问题 | 真实代码位置与语义 |
|---|---|
| loop 在哪里？ | `runtime/manual_agent_runtime.py` 的 `run()` 中，`while True` 按 LLM → Tool → LLM 顺序显式循环。 |
| state 在哪里？ | `runtime/base.py` 的 `AgentRunState`：`task_id`、`conversation_id`、step/tool 计数、runtime messages 和 status。只存在当前 Python 进程内。 |
| routing 在哪里？ | `run()` 中的 `if not response.tool_calls`、Tool 循环和异常分支。 |
| step limit 在哪里？ | 每次 Provider 调用前检查 `state.step_count >= max_steps`。 |
| tool execution 在哪里？ | Runtime 只调用项目 `ToolExecutor.execute()`；Executor 内部保留 Registry → Policy → validation → handler 路径。 |
| failure handling 在哪里？ | `AgentRuntimeError` 边界统一转换 Provider/limit/fatal Tool error，并发布 `agent.run.failed`。参数校验错误作为 Tool message 继续。 |

Manual Runtime 是 Reference Implementation。它的优点是控制流在一个函数内非常直接；缺点是执行状态没有 checkpoint boundary，不能在新 Runtime 实例中继续受控中断。

## LangGraphAgentRuntime

| 概念 | 对应实现 |
|---|---|
| 哪些变成 State？ | `runtime/langgraph/state.py` 的 `BankingAgentGraphState`：task/conversation ID、runtime messages、step/tool 计数、pending calls、final answer 和 structured error。 |
| 哪些变成 Node？ | `llm` node 负责 ContextBuilder、Provider 调用和回应解析；`tool` node 负责 budget 与顺序 ToolExecutor 调用。 |
| 哪些变成 Conditional Edge？ | `after_llm` 在 final/error/tool 之间路由；`after_tool` 在 fatal END 和继续 LLM 之间路由。Edge 由 Runtime 决定，不由模型输出 edge name。 |
| 哪些交给 Checkpointer？ | Graph State 和下一个 graph continuation point。`thread_id = task_id`，PostgreSQL saver 可让新 graph/runtime 实例从同一 Task checkpoint 继续。 |

Graph 拓扑为：

```text
START → llm
           ├─ final/error → END
           └─ tool_calls → tool
                              ├─ fatal → END
                              └─ continue → llm
```

项目自己的 `AGENT_MAX_STEPS` 和 `AGENT_MAX_TOOL_CALLS` 仍在 node 中检查，没有被 LangGraph recursion limit 替代。Node closure 捕获 Provider/Executor/Event sink，但这些对象不进入 Graph State 或 checkpoint。

## LangGraph 替代了什么？

- 手写 `while True` loop 的 orchestration 结构。
- 在一个函数里的 routing 分支，改为显式 node + conditional edge。
- 只在内存中的执行状态，对 LangGraph backend 增加 PostgreSQL checkpoint continuation。
- 受控实验中的中断/恢复机制。

## LangGraph 没有替代什么？

- `LLMProvider`、`FakeLLMProvider`、`OpenAICompatibleProvider`
- `ContextBuilder`
- `ToolRegistry`
- `PolicyService`
- `ToolExecutor` 和 Pydantic Tool schemas
- `MockBankService`
- Domain `Task`、`Conversation`、`Message`、`Event`
- Application API、`InProcessTaskRunner`、SSE 和前端
- 产品错误码、step/tool-call budget 和 Default Deny 安全语义
- Alembic 管理的 Application tables
- Audit/Event 事实

`LangGraph State ≠ Business State`，`LangGraph Checkpoint ≠ Domain Database`，`LangGraph Tool Node ≠ Tool Permission System`。

## 实际取舍

Manual Runtime 代码路径更短，适合审查最小 loop 语义。LangGraph Runtime 增加了 framework/checkpoint 依赖和运行基础设施，但用显式 topology 和 checkpoint continuation 换取了更清晰的节点边界与可恢复执行实验。当前没有证据支持删除 Manual Runtime，因此两者继续保留等待 Architecture Review。
