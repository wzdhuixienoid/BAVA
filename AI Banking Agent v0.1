# AI Banking Agent — Architecture Baseline v0.1

# 1. 项目定位

这个项目不是“银行版 ChatGPT”，也不是“六个业务 Agent 的集合”。

系统定位是：

> 一个能够理解用户金融意图、维护持续任务状态、组合银行及外部能力，并在高风险操作中通过确定性 Workflow、Policy、Approval 和认证机制安全执行的个人银行智能助理。

项目同时承担两个目标：

```text
目标 A
做出完整的 AI Banking Agent 产品

目标 B
通过这个项目真正理解 Agent Engineering
```

所以技术引入遵循：

> 先遇到问题，再引入技术；不为了展示 Agent、MCP、RAG、Multi-Agent 而强行使用。

------

# 2. 总体设计原则

Baseline v0.1 确定以下原则。

| 原则                            | 含义                                                         |
| ------------------------------- | ------------------------------------------------------------ |
| Workflow First, Agent Second    | 能确定性完成的业务不要强行 Agent 化                          |
| LLM ≠ Business System           | LLM 负责理解、判断、规划；业务系统负责事实和执行             |
| Default Deny                    | Agent 默认没有任何高风险权限                                 |
| Structured State > Conversation | 业务事实进入结构化 State，而不是依赖聊天历史                 |
| Tools for live data             | 实时账户、余额、交易等走 Tool/API                            |
| RAG for knowledge               | 产品说明、规则、FAQ 等非结构化知识走 RAG                     |
| Memory is hint, not truth       | 长期记忆不能作为金融操作事实来源                             |
| Human approval on side effects  | 不可逆/高风险操作必须有明确授权边界                          |
| Domain API > Agent API          | 前端连接 Banking Application，而不是直接连接 LangGraph/Agent |
| Modular Monolith First          | 第一版不做微服务                                             |
| Structured handoff              | Agent/Task 之间传结构化结果，不传内部思维链                  |
| Least Privilege                 | Agent、Skill、Workflow、Tool 都只有最小必要权限              |

一句话概括：

> **Agent 决定“应该做什么”，Workflow 控制“如何可靠完成”，Policy 决定“是否允许”，Tool 执行“具体能力”。**

------

# 3. 整体系统架构

Baseline 架构：

```text
                           USER
                            │
                            ▼
                  ┌───────────────────┐
                  │     Frontend      │
                  │                   │
                  │ Chat              │
                  │ Structured UI     │
                  │ Tasks             │
                  │ Reports           │
                  │ Approval          │
                  └─────────┬─────────┘
                            │
                     HTTP + SSE
                            │
                            ▼
                  ┌───────────────────┐
                  │ Banking App API   │
                  │                   │
                  │ Auth              │
                  │ Conversation      │
                  │ Task              │
                  │ Workflow          │
                  │ Approval          │
                  │ Events            │
                  └─────────┬─────────┘
                            │
                            ▼
                    ┌──────────────┐
                    │ Orchestrator │
                    └──────┬───────┘
                           │
                 Request Classification
                           │
         ┌─────────────────┼─────────────────┐
         ▼                 ▼                 ▼
       DIRECT            AGENTIC           PLANNED
         │                 │                 │
         ▼                 ▼                 ▼
        Tool              Agent            Plan
                                             │
                                         Task Graph
                                             │
                         ┌───────────────────┼─────────────┐
                         ▼                   ▼             ▼
                       Agent               Skill        Workflow
                         │                   │             │
                         └──────────┬────────┘             │
                                    ▼                     ▼
                              Tool Registry           Policy
                                    │                     │
                             ┌──────┴──────┐              ▼
                             ▼             ▼           Approval
                         Local Tool      MCP Tool          │
                                                           ▼
                                                      High-risk Tool
                                                           │
                                                           ▼
                                                    Mock Banking API
```

横向基础设施：

```text
Context Builder
Memory
Knowledge / RAG
Policy
Audit
Observability
Evaluation
```

------

# 4. 不按“菜单”拆 Multi-Agent

不采用：

```text
TransferAgent
BillAgent
CardAgent
SubscriptionAgent
...
```

这种一业务一个 Agent 的机械拆法。

Agent 边界主要依据：

```text
专业推理边界
上下文边界
工具边界
知识边界
权限边界
```

目前计划中的 Specialist Agent：

```text
BankingOrchestrator
    全局意图理解、Task规划和路由

FinancialAnalysisAgent
    消费、现金流、账单、订阅支出等分析

WealthAdvisorAgent
    后期加入
    理财产品搜索、比较和解释

LifestylePlanningAgent
    后期加入
    跨场景和长期任务规划
```

而这些不是 Agent：

```text
Transfer
Card Freeze
Subscription Cancellation
Investment Purchase
```

主要实现为确定性 Workflow。

Multi-Agent 是规模增长后的解耦机制，不是项目启动时的目标本身。

------

# 5. 四个核心执行概念

正式定义：

### Agent

使用 LLM 进行开放式理解、判断、选择和动态任务执行。

回答：

> “现在应该做什么？”

例如：

```text
FinancialAnalysisAgent
```

------

### Skill

封装一个可复用专业任务的：

```text
方法
步骤
约束
Input Schema
Output Schema
Allowed Tools
质量标准
Evaluation
```

回答：

> “这类任务怎样专业、稳定地完成？”

例如：

```text
MonthlySpendingReportSkill
SubscriptionAuditSkill
ProductComparisonSkill
RiskExplanationSkill
```

Skill 不拥有业务权限。

------

### Workflow

使用显式状态机控制有业务风险或严格执行顺序的过程。

回答：

> “这件事情必须按照什么状态和规则完成？”

例如：

```text
TransferWorkflow
CardFreezeWorkflow
SubscriptionCancellationWorkflow
InvestmentPurchaseWorkflow
```

------

### Tool

提供单一、结构化、有明确业务语义的能力。

回答：

> “系统具体能够做什么？”

例如：

```text
get_balance
search_transactions
resolve_payee
create_transfer_draft
execute_transfer
```

------

# 6. 请求按照四种模式路由

不是每个请求都进入 Planner。

```text
DIRECT

“余额多少？”
→ Tool
WORKFLOW

“给张三转2000”
→ TransferWorkflow
AGENTIC

“为什么这个月花这么多？”
→ FinancialAnalysisAgent
→ ReAct
PLANNED

“分析支出、找浪费订阅、
取消不需要的、再看看剩余资金如何安排”
→ Planner
→ Task Graph
→ Plan-and-Execute
```

因此：

> ReAct 是 Task 内部执行策略。

> Plan-and-Execute 是多个 Task 之间的 orchestration 策略。

二者可以同时存在。

Reflection 主要用于失败恢复和质量检查，而不是每一步必做。

------

# 7. 核心 Domain Model

系统核心对象正式确定为：

```text
Conversation
Plan
Task
Workflow
Approval
Operation
Event
```

关系：

```text
Conversation
      │
      ▼
     Plan
      │
      ▼
  Task Graph
      │
      ▼
    Task
      │
      ▼
   Executor
 Agent / Skill / Workflow / Tool
      │
      ▼
   Result
```

------

# 8. Conversation 与 Task 分离

Conversation 是：

> 用户和系统交互的容器。

Task 是：

> 系统真正执行工作的单元。

例如用户：

```text
“分析一下消费，
顺便把Netflix取消，
再给张三转500。”
```

不是一个 Task。

而是：

```text
T1 ANALYZE_SPENDING

T2 CANCEL_SUBSCRIPTION

T3 CREATE_TRANSFER
```

这样任务可以：

```text
独立暂停
独立失败
独立恢复
独立确认
独立审计
```

Conversation 生命周期与 Task 生命周期分离。

未来用户退出 App，Task 仍然可以存在。

------

# 9. Plan 是结构化 Task Graph

复杂用户目标生成 Plan。

例如：

```text
          Analyze Spending
                │
                ▼
           Generate Report

Detect Subscriptions
        │
        ▼
Analyze Usage
        │
        ▼
Cancellation Candidates
```

Task 支持：

```text
depends_on
condition
parallelizable
status
input
output
error
```

Planner 不能自由发明系统能力。

它只能从：

```text
Task Catalog
```

选择允许的 Task Type。

------

# 10. Task 和 Executor 解耦

Task 表示：

> 做什么。

Executor 表示：

> 怎么做。

例如：

```text
ANALYZE_SPENDING
→ FinancialAnalysisAgent

GENERATE_MONTHLY_REPORT
→ MonthlySpendingReportSkill

CREATE_TRANSFER
→ TransferWorkflow

GET_BALANCE
→ ToolExecutor
```

因此业务模型不会绑定某个 Agent Framework。

------

# 11. State 模型

State 不等于 Chat History。

我们至少区分：

```text
Conversation State

Task State

Workflow State

Execution State

UI State
```

Memory 和 Knowledge 独立。

关键原则：

> 语言不能代替系统状态。

例如用户在聊天中写：

```text
“确认”
```

不能自动意味着：

```text
Transfer.approved = true
```

正式 Approval 必须通过结构化业务事件产生。

------

# 12. Workflow 采用显式状态机

TransferWorkflow 示例：

```text
COLLECTING_INFORMATION
        │
        ▼
RESOLVING_PAYEE
        │
     ┌──┴────┐
     ▼       ▼
 UNIQUE   AMBIGUOUS
     │       │
     │       ▼
     │ NEED_SELECTION
     │       │
     └───┬───┘
         ▼
      VALIDATE
         │
         ▼
       REVIEW
         │
         ▼
 AWAITING_APPROVAL
         │
         ▼
   AUTHENTICATING
         │
         ▼
 FINAL_POLICY_CHECK
         │
         ▼
      EXECUTING
         │
      ┌──┴───┐
      ▼      ▼
   SUCCESS UNKNOWN / FAILED
```

Workflow 内部尽可能使用：

```text
结构化 State
Event
Tool Result
业务规则
```

而不是不断 Prompt → Prompt → Prompt。

------

# 13. Event 驱动状态变化

基本思想：

```text
State + Event → New State
```

例如：

```text
AWAITING_APPROVAL
+
ApprovalGranted
↓
AUTHENTICATING
```

典型 Event：

```text
UserProvidedInformation
PayeeSelected
ValidationPassed
ApprovalGranted
ApprovalRejected
AuthenticationSucceeded
ExecutionSucceeded
ExecutionFailed
CancelRequested
Timeout
```

Event 为：

```text
恢复
审计
前端同步
测试
```

提供基础。

------

# 14. Agent / Skill / Workflow / Tool 权限边界

大致矩阵：

| Component              | Read Tool | Write Tool | Skills | Workflow  |
| ---------------------- | --------- | ---------- | ------ | --------- |
| Orchestrator           | 极少      | 否         | 极少   | 创建 Task |
| FinancialAnalysisAgent | 是        | 否         | 是     | 只能提议  |
| WealthAdvisorAgent     | 是        | Draft only | 是     | 只能提议  |
| LifestyleAgent         | 必要范围  | 否         | 是     | 只能提议  |
| ReportSkill            | allowlist | 否         | —      | 否        |
| TransferWorkflow       | 是        | 是         | 通常否 | —         |

关键规则：

> 高风险 Tool 只暴露给受控 Workflow。

例如：

```text
execute_transfer
```

FinancialAnalysisAgent 根本看不到。

------

# 15. Tool Design Pattern

高风险业务采用：

```text
READ
↓
DRAFT
↓
VALIDATE
↓
APPROVE
↓
COMMIT
↓
VERIFY
```

转账例如：

```text
resolve_payee

get_transfer_limits

create_transfer_draft

validate_transfer

execute_transfer

get_transfer_status
```

拒绝设计成：

```text
transfer_money_everything()
```

同样避免数据库级 Tool：

```text
execute_sql
update_row
```

Tool 的粒度应该是：

> 一个明确的业务能力 + 一个清晰的副作用边界。

------

# 16. Registry 设计

系统以后有四个基本 Registry：

```text
AgentRegistry

SkillRegistry

WorkflowRegistry

ToolRegistry
```

未来可以进一步形成：

```text
CapabilityRegistry
```

每个 Capability 描述：

```text
id
version
description
input_schema
output_schema
risk_level
required_permissions
allowed_callers
```

V0.1 不做复杂抽象。

最初 Python dict / 明确配置完全可以。

------

# 17. Skill Architecture

Skill 不等于大 Prompt。

一个 Skill 未来可以包含：

```text
skills/
└── monthly-spending-report/
    ├── SKILL.md
    ├── schema
    ├── instructions
    ├── resources
    └── tests
```

Skill 描述：

```text
Inputs
Outputs
Procedure
Allowed Tools
Validation Rules
Examples
Evaluation Cases
```

MonthlySpendingReportSkill：

```text
数据完整性检查
↓
总支出
↓
分类分析
↓
环比
↓
异常
↓
固定支出
↓
解释
↓
报告
↓
Quality Check
```

数字计算由：

```text
Python / SQL / Tool
```

完成。

LLM主要负责：

```text
语义
分析
解释
表达
```

------

# 18. Context Architecture

核心原则：

> Context ≠ Full Conversation History。

所有 Agent Context 由：

```text
Context Builder
```

针对当前 Task 动态构建。

```text
Conversation ──────┐
                   │
Task State ────────┤
                   │
Memory ────────────┤
                   ▼
             Context Builder
                   ▲
RAG ───────────────┤
                   │
Tool Results ──────┘
                   │
                   ▼
             Context Envelope
                   │
                   ▼
                 Agent
```

只给 Agent：

> minimum necessary context。

------

# 19. Context Trust Hierarchy

业务事实可信度原则：

```text
Live Business Data
        ↑
Persistent Workflow State
        ↑
Verified User Profile
        ↑
Explicit Memory
        ↑
Inferred Memory
        ↑
Conversation Interpretation
        ↑
LLM Guess
```

高层来源与低层冲突时，高层优先。

例如：

```text
Memory：
工资卡是默认账户

Bank API：
工资卡已关闭
```

Bank API 胜出。

------

# 20. Memory Design

V1 Memory 非常克制。

实现：

```text
Conversation Context

Structured Task / Workflow State

少量 Explicit User Preferences
```

暂不实现：

```text
自动长期记忆
Memory Reflection
Memory Consolidation
Memory Embedding
Memory Decay
```

长期 Memory：

```text
结构化
有来源
有时间
可失效
```

并且：

> Memory 可以帮助填充候选信息，但不能代替金融操作确认。

------

# 21. 敏感信息原则

以下信息不得进入普通 LLM Context / Memory：

```text
OTP
Password
CVV
Authentication Token
完整卡号
API Key
安全答案
```

Credential 走：

```text
Agent
↓
Tool Runtime
↓
Credential Manager
↓
External API
```

Agent永远拿不到 Credential。

------

# 22. RAG Boundary

严格区分：

```text
Operational Data
→ Tool / API

Knowledge
→ RAG
```

例如：

```text
余额
交易
银行卡状态
订单状态
实时收益
→ Tool
产品说明
手续费规则
赎回规则
FAQ
服务协议
→ RAG
```

RAG 文档保留：

```text
document_id
version
source
effective_from
effective_to
scope
```

V1 只预留 Knowledge 接口。

真正 RAG 等 WealthAdvisor 阶段再引入。

------

# 23. Multi-Agent Context Isolation

Agent 不共享完整上下文。

例如：

```text
FinancialAnalysisAgent
```

向：

```text
WealthAdvisorAgent
```

传递：

```json
{
  "monthly_surplus": 5000,
  "available_cash": 20000
}
```

而不是：

```text
整个聊天历史
所有Tool调用
所有内部推理
```

原则：

> Share results and evidence, not hidden reasoning.

------

# 24. Security Architecture

安全分为：

```text
Authentication
Authorization
Policy
Approval
Execution Control
```

不能混成一个：

```text
is_allowed = true
```

基本路径：

```text
User
↓
Authentication
↓
Authorization
↓
Workflow
↓
Policy
↓
Approval
↓
Re-authentication
↓
Final Policy Check
↓
Commit
```

------

# 25. Default Deny + Least Privilege

每一个执行者都是 Principal：

```text
user:123

agent:financial-analysis

workflow:transfer
```

Tool 调用要求：

```text
User Permission
AND
Executor Permission
```

用户本人有转账权限，并不意味着：

```text
FinancialAnalysisAgent
```

可以执行转账。

------

# 26. Tool Risk Levels

Baseline：

```text
R0
Public Read

R1
Private Read

R2
Low-risk Write

R3
Sensitive Write

R4
Financial Commit
```

R4：

```text
转账
投资申购
投资赎回
```

必须：

```text
Draft
Policy
Approval
Re-auth
Idempotency
Commit
Verify
Audit
```

------

# 27. Policy Engine

独立：

```text
PolicyService
```

而不是把安全规则散落到 Prompt。

Policy 可以返回：

```text
ALLOW

DENY

REQUIRE_APPROVAL

REQUIRE_REAUTH

REQUIRE_APPROVAL_AND_REAUTH

REQUIRE_SUITABILITY_CHECK
```

高风险 Tool 经过统一：

```text
Tool Gateway / Policy Enforcement Point
```

防止调用者绕开 Policy。

------

# 28. Approval 是正式 Domain Object

不是：

```text
confirmed = true
```

而是：

```text
Approval
```

至少包含：

```text
approval_id
workflow_id
payload_hash
status
created_at
expires_at
approved_at
```

状态：

```text
PENDING
APPROVED
REJECTED
EXPIRED
CONSUMED
INVALIDATED
```

Approval 绑定具体 Action Snapshot。

例如：

```text
账户
收款人
金额
手续费
备注
```

关键字段发生变化后：

```text
旧 Approval 自动失效
```

------

# 29. Operation / Idempotency

真正副作用由：

```text
Operation
```

表示。

状态包括：

```text
CREATED
SUBMITTED
UNKNOWN
SUCCEEDED
FAILED
```

每个 Operation：

```text
operation_id
idempotency_key
```

Timeout：

```text
≠ FAILED
```

而可能：

```text
UNKNOWN
↓
query_status
```

绝不能盲目重复转账。

------

# 30. Prompt Injection 的安全目标

系统不是假设：

> Prompt Injection 永远不会成功。

而是假设：

> 即使 Agent 被误导，也不能增加 Authority。

所以恶意文本最多应该导致：

```text
错误分析
错误建议
```

而不能：

```text
获得新Tool
扩大权限
绕过Approval
绕过Policy
获取Credential
执行转账
```

这叫：

> Prompt Injection must not change authority.

------

# 31. MCP Boundary

未来 MCP 位于 Tool Layer。

```text
Agent / Skill / Workflow
          │
          ▼
      Tool Registry
          │
     ┌────┴─────┐
     ▼          ▼
Local Tool    MCP Adapter
                  │
                  ▼
             MCP Server
```

MCP Tool 不自动可信。

必须经过：

```text
Discovery
Allowlist
Internal ToolSpec
Policy Metadata
Permission
```

Agent 不需要知道 Tool 是：

```text
Python Function
MCP
HTTP API
```

------

# 32. Frontend Product Model

前端不是单纯 Chat UI。

定位为：

> Agent Workspace。

至少包含：

```text
Chat
Structured Cards
Task Status
Reports
Approval
Receipts
```

未来主要页面：

```text
Agent Workspace

Tasks

Reports

Mock Accounts
```

------

# 33. Server State 与 Client State 分离

服务器是以下状态的唯一真相源：

```text
Conversation
Task
Workflow
Approval
Operation
Report
```

Frontend：

```text
只负责展示
```

例如：

```text
approved = true
```

不能由 React state 决定。

------

# 34. API Boundary

Frontend 连接：

```text
Banking Application API
```

永远不直接连接：

```text
LangGraph
FinancialAnalysisAgent
TransferAgent
```

V1 API 资源概念：

```text
/auth

/conversations
/conversations/{id}/messages

/tasks
/tasks/{id}

/workflows/{id}
/workflows/{id}/actions

/approvals/{id}
/approvals/{id}/decision

/reports/{id}

/events
```

不是每个资源都需要完整 CRUD。

------

# 35. Natural Language 和 Structured Action 分离

用户输入：

```text
“给张三转2000”
```

通过：

```text
Message API
```

用户点击：

```text
[确认转账]
```

通过：

```text
Approval / Action API
```

而不是再发：

```text
message = "确认"
```

原则：

> Natural language enters through Message API; deterministic UI interactions enter through Action API.

------

# 36. 前后端通信

第一版：

```text
HTTP + SSE
```

不急着 WebSocket。

职责：

```text
REST/resource API
= source of truth

SSE
= realtime notification
```

刷新网页后通过 Resource API 重新恢复状态。

------

# 37. Event Protocol

统一 Event Envelope，例如：

```text
event_id
event_type
timestamp
conversation_id
plan_id
task_id
workflow_id
sequence
data
```

Event 使用 Domain 名称，而不是 Agent 名称。

例如：

```text
task.created
task.started
task.progress
task.completed
task.failed

workflow.created
workflow.state_changed

approval.required
approval.resolved

operation.started
operation.completed

report.generated

conversation.message.delta
conversation.message.completed
```

不要：

```text
financial_agent_finished
```

------

# 38. 不暴露 Chain-of-Thought

允许前端看到：

```text
正在获取交易
正在分析消费
正在生成报告
```

不允许：

```text
LLM内部Thought
Agent之间内部消息
完整Prompt
隐藏推理
敏感Tool参数
```

UI Progress 是：

```text
Structured Runtime Status
```

不是伪装后的 Chain-of-Thought。

------

# 39. UI Component Registry

不允许 LLM 随意发明前端组件。

允许的 UI 类型由系统注册。

例如：

```text
AccountSummary
TransactionList
SpendingChart
MonthlyReport
PayeeSelector
TransferReview
ApprovalCard
TransferReceipt
TaskProgress
ErrorCard
```

而且优先：

```text
Domain Result
↓
Presenter
↓
UI
```

而不是：

```text
LLM
↓
直接生成UI指令
```

------

# 40. Artifact ≠ Message

报告、回执、计划等正式结果是独立 Resource。

例如：

```text
MonthlySpendingReport

TransferReceipt
```

聊天里可以引用：

```text
report_id
receipt_id
```

而不是把整个报告永久塞进 Message。

这为以后：

```text
Reports 页面
历史任务
再次打开
导出
```

留下基础。

------

# 41. 前后端 Schema

Backend：

```text
Pydantic
FastAPI OpenAPI
```

Frontend：

```text
生成 TypeScript API types/client
```

避免人工维护两套 Schema。

因此我们之前设想的：

```text
packages/schemas
```

可以调整为：

```text
packages/api-client
```

由 OpenAPI 自动生成。

------

# 42. 技术栈 Baseline

目前建议：

```text
Repository
Monorepo

Frontend
Next.js
React
TypeScript
Tailwind
shadcn/ui

Backend
Python
FastAPI
Pydantic

Agent Runtime
LangGraph
但不允许 Domain Model 依赖 LangGraph

Database
PostgreSQL

Cache / ephemeral runtime
Redis
按需要逐步使用

Streaming
SSE

Bank backend
Mock Banking Service

LLM
Provider abstraction

RAG
暂缓实现

MCP
暂缓实现

Deployment
Docker Compose
```

架构风格：

```text
Modular Monolith
```

第一阶段禁止因为“未来扩展”提前拆微服务。

------

# 43. Repository Baseline

大致：

```text
ai-banking-agent/

├── apps/
│   ├── web/
│   └── api/
│
├── packages/
│   └── api-client/
│
├── docs/
│
├── infra/
│
├── scripts/
│
├── tests/
│
├── docker-compose.yml
└── README.md
```

Backend 内部预计：

```text
api/
domain/
agents/
skills/
workflows/
tools/
policy/
context/
memory/
knowledge/
services/
runtime/
events/
audit/
mock_bank/
```

这里暂时只确定领域边界。

**不要现在抽象几十层 BaseClass。**

------

# 44. V1 不是什么

Baseline v0.1 明确暂不实现：

```text
完整Multi-Agent体系

WealthAdvisorAgent

LifestylePlanningAgent

真正RAG

Vector DB

MCP Server

复杂长期Memory

自动Memory extraction

Agent-to-Agent自由通信

微服务

Kafka

Kubernetes

完整生产银行认证

真实支付接口
```

这些不是被否定。

只是：

> 目前没有足够问题需要它们。

------

# 45. 第一阶段真正实现什么

V1 只需要证明两类 Agent 系统。

### Vertical Slice A：开放式认知任务

```text
“分析8月份消费并给我报告。”
```

完整链路：

```text
Frontend
↓
Conversation API
↓
Orchestrator
↓
ANALYZE_SPENDING Task
↓
FinancialAnalysisAgent
↓
Read Tools
↓
Structured Analysis Result
↓
MonthlySpendingReportSkill
↓
Report Artifact
↓
Frontend Report View
```

学习：

```text
ReAct
Tool Calling
Skill
Context
Structured Output
Streaming
Agent UI
```

------

### Vertical Slice B：高风险事务任务

```text
“给张三转2000。”
```

完整链路：

```text
Frontend
↓
Conversation API
↓
Orchestrator
↓
TransferWorkflow
↓
Resolve Payee
↓
Draft
↓
Policy
↓
Approval
↓
Re-auth
↓
Final Policy
↓
Operation
↓
execute_transfer
↓
Verify
↓
Audit
↓
Receipt
```

学习：

```text
Workflow
State Machine
Human-in-the-loop
Policy
Permissions
Idempotency
Structured UI
Safety Boundary
```

这两个案例已经足以覆盖我们第一阶段真正想学习的核心能力。

------

# 46. Codex 第一轮不应该做什么

第一次给 Codex 的任务**不是**：

> 帮我实现完整 AI Banking Agent。

而应该是：

```text
按照 Architecture Baseline v0.1
建立一个可运行的系统骨架。
```

第一轮目标仅仅是：

```text
Monorepo 能跑

Frontend 能打开

FastAPI 能跑

PostgreSQL 能连接

Domain Models 存在

Registry Skeleton 存在

MockBankService 存在

Policy Skeleton 存在

Conversation API 存在

Task Model 存在

SSE 能连接

Frontend 可以发送消息

Backend 创建一个简单Task

Frontend通过SSE看到Task变化
```

此时：

```text
没有真正LLM
没有真正ReAct
没有Transfer执行
没有RAG
没有MCP
```

完全可以。

先验证整个“骨架”是通的。

------

# 47. Architecture Baseline v0.1 的冻结范围

从现在开始，在出现明确工程问题之前，我们暂时冻结下面这些决策：

```text
Agent / Skill / Workflow / Tool 的定义

Workflow-first原则

Task Graph orchestration

Domain State独立于Agent framework

Structured Handoff

Context Builder

Explicit Memory first

Tools for operational data

RAG for knowledge

Default Deny

Policy / Approval / Operation模型

Agent不直接拥有Financial Commit权限

HTTP + SSE

Message API与Action API分离

Server State authoritative

Domain Event协议

Artifact独立于Message

Modular Monolith

Next.js + FastAPI
```

后续如果实现证明某条设计不合理：

> **允许修改架构。**

Baseline 是“当前最佳假设”，不是不可更改的教条。

------

## 最终可以把整个 v0.1 压缩成这一张图

```text
                         USER
                           │
                           ▼
                  ┌─────────────────┐
                  │ Agent Workspace │
                  │ Chat / Tasks    │
                  │ Report/Approval │
                  └────────┬────────┘
                           │
                       HTTP/SSE
                           │
                           ▼
                 ┌──────────────────┐
                 │ Banking App API  │
                 └────────┬─────────┘
                          │
                          ▼
                    Orchestrator
                          │
                classify / plan
                          │
           ┌──────────────┼──────────────┐
           ▼              ▼              ▼
         DIRECT         AGENTIC        PLANNED
           │              │              │
           ▼              ▼              ▼
          Tool          Agent          Task Graph
                          │              │
                        Skill     ┌───────┼───────┐
                          │       ▼       ▼       ▼
                          │     Agent   Skill  Workflow
                          │       │       │       │
                          └───────┴───┬───┘       │
                                      ▼           ▼
                                Tool Registry   Policy
                                      │           │
                                Read Tools    Approval
                                                  │
                                                Re-auth
                                                  │
                                             Final Policy
                                                  │
                                              Operation
                                                  │
                                              Tool Gateway
                                                  │
                                                  ▼
                                          High-risk Tools
                                                  │
                                                  ▼
                                           Mock Bank API


     Context Builder        Memory         Knowledge/RAG
            │                  │                 │
            └──────────────────┼─────────────────┘

     State / Events          Audit          Observability
```