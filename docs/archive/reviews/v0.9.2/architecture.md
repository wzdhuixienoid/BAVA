# 历史档案：当前系统架构

> 历史材料，保留原记录日期、版本和结论。旧风险规则、待办事项、测试数量与本地部署状态不代表 v0.10.3；当前说明见 [文档导航](../../../README.md)。

v0.9.2，2026-10-05。部署是**模块化单体**：Web、API、PostgreSQL三个Compose服务；API进程托管三个专用worker loop。图中模块不代表独立微服务，三个Agent不代表自由协商的Multi-Agent。

可直接打开 [完整SVG图](assets/system-architecture.svg) 或 [PNG图](assets/system-architecture.png)。下列Mermaid是可编辑的结构源。

## 1. 总体架构

```mermaid
flowchart TB
    U[用户中文文本与确认动作] --> W[Next.js Web\n工作台 / Dashboard / Reports / Subscriptions]
    I[可选OIDC IdP\n当前为development Principal] --> A
    W -->|HTTP / Bearer + fetch SSE| A[FastAPI Domain API\n认证 / owner scope / typed DTO]
    A --> C[ConversationService\nMessage + Task + Event + Outbox原子提交]
    C --> DB[(Application PostgreSQL\nAlembic head 0017)]
    DB --> TW[TaskExecutionWorker\nclaim / lease / heartbeat / attempt fence]
    TW --> R[InProcessTaskRunner + RequestRouter]
    R --> AG[只读Agent定义\nMinimal / Financial / Subscription]
    AG --> LG[LangGraph Runtime\nLLM node ↔ Tool node]
    LG --> TE[ToolRegistry → Policy → ToolExecutor]
    R --> WF[确定性Workflow\nTransfer / SubscriptionCancel]
    R --> P[ConstrainedPlanner → PlanValidator\n持久Plan DAG]
    P --> PE[PlanExecutionService\n复用同一Task Worker]
    PE --> AG
    PE --> CO[确定性CONDITION\ntyped source + Decimal + Decision hash]
    CO -->|TRUE| WF
    CO -->|FALSE| SK[guarded Step SKIPPED\n零业务写资源]
    PE --> WF
    TE --> DS[只读Domain服务\nMockBank / FinancialAnalytics / Subscription / Anomaly]
    DS --> FD[(committed synthetic JSON\n4账户 / 140交易 / 6收款人 / 5合同)]
    LG --> SS[FinancialAnalysisSnapshot]
    SS --> S[MonthlySpendingReportSkill\nPython core +受校验LLM说明]
    S --> RA[immutable Report Artifact]
    RA --> DB
    WF --> G[Risk / Approval / RED Reauth / SecurityGuard\n版本 / canonical hash / TTL / 用户锁]
    G --> O[OperationService\n授权消费+Operation+Workflow+Event/Outbox同事务]
    O --> TE
    TE -->|仅对应Workflow可调用写Tool| PR[MockTransferProvider / MockSubscriptionProvider\n固定幂等key / 持久ledger / 账户锁]
    PR --> DB
    OR[OperationRecoveryWorker\n只恢复既有Operation] --> O
    DB --> OR
    DB --> OP[OutboxPublisher\nlease / 至少一次发布]
    OP --> EB[进程内EventBus → SSE]
    EB -->|提示重新GET| W
    DB --> AP[只读Projection\nDashboard / Workflow presentation / Audit]
    AP --> A
    LG --> CP[(LangGraph checkpoint tables\n与业务状态职责分开)]
    LLM[OpenAI-compatible LLM Provider\n只理解、选择、解释] -.-> R
    LLM -.-> LG
    LLM -.-> P
    LLM -.-> S
```

Dashboard直接复用Domain服务与格式化器，不必经过Agent或LLM。独立业务、报告和简单查询仍走原路径，需要跨能力才进入Plan。CONDITION不是Tool/Agent Capability，TRUE不授权，FALSE跳过写步骤。

## 2. 转账写入时序

```mermaid
sequenceDiagram
    actor U as 用户
    participant API as Domain API
    participant W as Transfer Workflow
    participant DB as Application PostgreSQL
    participant P as Mock Transfer Provider
    participant RW as Recovery Worker
    U->>API: 中文转账请求
    API->>DB: Message / Task / Event / Outbox
    API-->>U: 202 + Task ID
    Note over API,W: Task Worker → Router → 意图提取；LLM随后退出写入路径
    W->>W: 收款人 / 账户 / 金额 / 币种 / 余额校验
    W->>DB: 草稿 + RiskDecision
    W-->>U: READY_FOR_REVIEW，必要时选择候选
    U->>W: 明确Approval，expected_version
    W->>DB: payload hash绑定授权
    opt RED
        U->>W: Mock challenge与验证
        W->>DB: 绑定Approval的Reauth VERIFIED
    end
    W-->>U: READY_FOR_COMMIT，仍未提交
    U->>W: 提交
    W->>DB: Security user lock → Risk user lock
    W->>W: 重读exposure、风险与所有授权/业务校验
    alt YELLOW升级RED
        W->>DB: REAUTH_REQUIRED，不创建Operation
        W-->>U: 补强验证
    else 控制有效
        W->>DB: Operation CREATED + Approval CONSUMED + Workflow COMMITTING + Events/Outbox
        Note over W,P: 应用事务提交，随后执行Provider I/O
        W->>P: 写Tool仅传operation_id，加载固定payload/key
        P->>DB: 账户锁、重查幂等key与余额、原子ledger
        alt Provider最终结果明确
            P-->>W: SUCCEEDED / FAILED
            W->>DB: Operation / Workflow最终状态 + Events/Outbox
        else 超时或结果不明
            W->>DB: UNKNOWN / 持久reconcile调度
            RW->>P: 仅查询同一key / 原Operation
            P-->>RW: 最终状态
            RW->>DB: fence检查 + 最终状态 + Events/Outbox
        end
    end
    API-->>U: typed状态 / 回执 / Audit
```

此时序省略订阅取消的对应路径：它固定YELLOW，不使用转账日累计和RED Reauth，采用自己的取消Provider/ledger，但共用Approval、Operation、Guard、Recovery、Event/Outbox框架。

## 3. 三种持久化职责

| 存储 | 内容 | 谁管理/用途 |
|---|---|---|
| Application PostgreSQL | Conversation、Message、Task、Event、Report、Workflow、Approval、Reauthentication、Operation、Outbox、identity mapping、Guard、Plan/Step/Dependency、Mock ledger | Alembic；业务事实、ownership、授权、任务调度和并发控制 |
| LangGraph PostgreSQL表 | checkpoint_migrations、checkpoints、checkpoint_blobs、checkpoint_writes | AsyncPostgresSaver；只保存Agent Runtime执行快照，不决定资金业务状态 |
| committed JSON | 合成账户基线、交易、收款人、订阅和Golden | MockBankService只读；有效余额减去成功ledger转出，取消ledger覆盖合同有效状态 |

应用库和checkpoint可以使用同一PostgreSQL实例/数据库，但表所有权不同。reset要求配置指向同一数据库以事务化清理所属用户状态；不是删除库/volume。

## 4. 安全与事实边界

| 边界 | 当前规则 |
|---|---|
| 身份 | 外部JWT经服务器验证与identity mapping；worker从Task/Conversation ownership构造ExecutionPrincipal。浏览器/LLM不能选择user_id |
| 工具 | Registry显式注册；Policy匹配caller、allowlist、risk_level和side_effect；默认拒绝。两个写Tool仅允许对应Workflow |
| 业务写入 | Workflow、Approval/hash/TTL、RED验证、Guard、commit-time风险、Operation与Provider多层控制 |
| 并发 | Guard用户锁→Risk用户锁保护新Operation；Provider账户锁保护余额；固定key/唯一约束保护重放；lease/fencing保护worker结果 |
| 金融事实 | Decimal+typed result；UI消费后端display和状态；LLM自然语言只作解释，双SUCCEEDED才显示业务成功 |
| 条件 | 读已完成typed source，用Decimal判断并持久Decision；FALSE直接SKIPPED。原文句式/币种未识别的缺口见R02/R03 |
| 审计 | 持久事件历史与当前资源分开，owner-scoped，有限payload与hash；不保存OTP/JWT/API key/隐藏推理，无WORM防篡改 |
| 通知 | Event+Outbox原子，至少一次发布；EventBus进程内，无跨进程保证或SSE replay，资源API是事实源 |

当前没有真实银行/商户连接、真实MFA、手机APP/IM/语音、RAG/向量库、长期记忆、通用代码执行沙箱、Celery/Redis/Kafka或自由Multi-Agent。示意中的OIDC是已实现认证边界的可选接入，不表示已配置生产IdP。

主要源码：`main.py`、`runtime/task_runner.py`、`application/operation_service.py`、`application/plan_execution_service.py`、`runtime/*worker.py`、`runtime/outbox_publisher.py`、`audit/projection.py`。
