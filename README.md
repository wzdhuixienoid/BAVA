# AI Banking Agent

当前版本：`v0.10.2`；数据库迁移：`0030`。

版本主题：转账备注、单次与有限次按月预约、站内 AA 收款、收款人编辑删除，以及预约和对话管理完善。手机号转账已移除，当前转账目标通过已登记的银行卡收款人或 AA 发布快照确定。

面向中文用户的个人银行 Agent 应用，支持账户与余额查询、消费分析、月度／年度报告、确定性异常提示、订阅管理、安全转账、预约与周期转账和 AA 收款。所有银行操作、强身份验证与 AA 参与者流程均为 Mock；不接入真实银行、不发送短信、不集成外部支付。

Task 完成、预约创建或 AA 请求发布都不代表付款成功；只有 Provider 明确成功且原 Operation 已收敛才显示付款成功。`UNKNOWN` 持续查询原 Operation，不能另建扣款。

本版功能与授权说明见 [智能转账指南](report/08-intelligent-transfer-guide.md)，实际检查范围见 [验证记录](report/09-transfer-extensions-validation.md)。历史版本测试与报告保留原日期和版本，不视为本版重新运行的结果。

核心设计原则：金融金额、分类汇总、占比、排名和环比全部由确定性 Python `Decimal` 代码计算；LLM 只负责意图识别、工具选择和基于可信事实的自然语言解释。

核心场景覆盖：

1. 智能转账        `COMPLETE`
2. 账单分析        `COMPLETE`
5. 订阅 / 代扣管理 `COMPLETE`

已达到赛题“至少 3 个核心场景”的要求。

模拟账单现覆盖 **2025-01-01 至 2026-10-07**：**1,207 笔**、21 个完整自然月及本月部分数据，包含工资、奖金、退款、分类消费、订阅历史价格变化、转账双边记录、待入账与撤销，以及四类异常规则样例。数据固定种子生成；旧七八月黄金结果保持一致。账单由 Mock Bank 读取 JSON fixture，PostgreSQL 保存对话、业务和审计记录；扩容通过更新 fixture 与重启 API 生效，无需清空数据库。

重新生成与校验（Python 3.12 环境）：

```bash
apps/api/.venv/bin/python scripts/generate_mock_data.py
apps/api/.venv/bin/python scripts/generate_golden_financial_metrics.py
apps/api/.venv/bin/python scripts/validate_mock_data.py
```

未指定天数或起止时间的近期消费默认使用当前业务时间向前30天到当前时间，回答说明所用期间；本月使用当前业务月。未提供年份的月份按业务参考日期补全年份。年度聚合使用自然年，与上年比较。无完整账单数据时说明原因，不生成空报告。报告存储类型与 Skill ID 保留现有月度标识以兼容历史数据，由 `period`（`YYYY`／`YYYY-MM`）区分年度与月度。

指定“最近 N 天”或“N 天消费”时，从当前业务参考时间向前 N 天到当前时间进行汇总、分类和主要交易查询，支持跨月、跨年。各工具共享固定区间；区间比较使用紧邻的等长前期。工具也接受带时区的 `start_at` / `end_at` 明确区间，或 `recent_days`，三种期间参数互斥。区间为左闭右开。普通消费分析不会调用异常识别；只有本次用户明确要求异常检查时才提供该工具。无法确定天数或日期时先说明缺少的信息。

异常分析支持一年以内的天数和起止时间；“近一年”使用当前时间向前一个日历年。每笔交易的比较基线为前90天，优先同商户同分类（至少3笔），其次同分类（至少8笔）；不拿房租与餐饮小额交易混合比较。已证实按月出现的同商户支出按自身历史比较，金额上涨至少30%才提示，稳定房租不反复报警。快照记录比较范围、可用交易时间、样本不足的笔数、异常总数及截断标记。异常分析Skill统一组织中文说明和表格，金额（元）与倍数保留两位小数，不显示币种列。完整明细最多展示最近50笔并明确截断。

消费汇总自动在同期间、同账户和同用户范围执行检查，以 `spending_review` 保留最多3笔优先核对提示（重复扣款、订阅涨价优先）。普通回答附简短提示，报告保存该段快照；明确询问异常时才展开完整明细。用户明确拒绝异常检查时不执行自动检查。超过一年或历史不足时明确说明限制，仍正常完成消费汇总；未检出不表示安全或排除欺诈。自动检查在汇总工具内完成，不额外消耗模型工具调用预算，也不修改历史报告。

## 当前能力

| 用户需求 | 执行者 | 能力 |
|---|---|---|
| 查看账户、查询余额 | `agent:minimal-banking` | `account.list`、`account.get_balance` → typed `AccountListResult` / `AccountBalanceResult` |
| 金融总览 Dashboard | 只读 Domain API projection | 有效账户余额、月收入/支出/环比、分类分布、主要交易、订阅成本与异常卡片 |
| 风险、业务流程与条件展示 | 后端 typed presentation → Web UI | RiskDecision、Workflow 时间线、真实 DAG / Guard、Condition TRUE/FALSE、集中中文状态 |
| 审计证据链 | owner-scoped 只读 Domain API | 持久 Event、风险历史、授权 hash、Guard、Operation / Provider、Condition 零写入证据；不暴露隐藏推理或凭证 |
| Demo readiness / preflight | dev/test-only 只读 projection + CLI | version/head、初始余额/exposure、订阅、Guard、Mock modes 与无未收敛 Operation |
| 月度／年度支出、分类、环比／同比、主要交易分析 | `agent:financial-analysis` | 四个只读 Financial Tools |
| 异常交易分析 | `agent:financial-analysis` | `transaction.detect_anomalies` → 确定性快照 → `skill:transaction-anomaly-analysis` → 单条助理回答 |
| 生成月度／年度消费报告 | Financial Agent + `skill:monthly-spending-report` | Snapshot → immutable Report Artifact |
| 订阅分析 | `agent:subscription-analysis` | 自动识别周期扣费、按币种成本、涨价、即将续费 |
| 订阅管理分类 | deterministic Subscription service | `MANAGED` / `DETECTED_ONLY`，仅合同可管理者允许取消 |
| 查询、新增、编辑与删除收款人 | 只读 Agent + `/payees` Domain API | 对话列表／搜索；页面核对后确认保存，按用户持久化，重复保存去重 |
| 对话名称 | Conversation service + 工作台 | 手动编辑名称；首条回复按首个请求自动命名；手动名称保留 |
| 删除对话 | Conversation service + 工作台 | 软删除、未授权及资金处理中流程拦截；已授权预约独立继续执行，保留业务与审计记录 |
| 恢复订阅续费授权 | `workflow:subscription-resume` | RED → Approval → Reauthentication → Operation；恢复原套餐，本次不扣款 |
| 安全取消订阅 | `workflow:subscription-cancel` | YELLOW → Approval → Operation → MockSubscriptionProvider |
| 风险控制 | deterministic Risk Policy | GREEN 查询自动执行；YELLOW 管理写操作确认；所有转账与恢复续费授权均 RED 确认 + 强验证 |
| 转账全链路 | `workflow:transfer` | 收款人选择 → Draft → Validation → RED → Approval → Reauthentication → Operation |
| 转账备注 | 同一 Transfer Workflow | 最多 100 个 Unicode 字符；备注纳入确认哈希，修改后重新确认及强验证，历史保留提交快照 |
| 单次及按月周期预约 | ScheduleService + ScheduleWorker | 核对 → 确认 → 强验证 → 显式授权创建；到时自动执行 Mock 转账，持久化 lease、限定执行窗口与每期唯一 Operation |
| AA 收款与付款 | AAService + 既有 Transfer Workflow | 平均或手动按整数分分摊；发起者自己承担；其他参与者独立授权，Provider 成功后入账 |
| Operation 自动恢复 | PostgreSQL-backed recovery worker | due scan → `SKIP LOCKED` claim → lease → reconcile → retry/terminal |
| 并发转账资金安全 | `MockTransferProvider` | account-scoped advisory lock → authoritative balance → atomic ledger fact |
| 并发转账认证安全 | Application Risk Gate | user-scoped advisory lock → fresh daily exposure → controls → Operation |
| 安全熔断 | `SecurityGuardService` | 3 次连续强验证失败 / 10 min，或 5 次控制绕过 / 5 min → `WRITE_LOCKED` 15 min |
| 持久事件发布 | Transactional Outbox | Event + Outbox atomic commit → leased publisher → EventBus/SSE |
| 持久 Task 执行 | PostgreSQL-backed Task worker | due scan → `SKIP LOCKED` claim → lease/heartbeat/fencing → retry/terminal |
| 受约束复杂任务规划 | `ConstrainedPlanner` + `PlanValidator` | 只选已有高层 Capability，最多 8 步、一个写 Workflow |
| 持久化 Task DAG | `PlanExecutionService` + 现有 Task worker | attempt fencing、幂等恢复、用户等待、人工接管、只读回退 |
| 可信身份与多用户隔离（OIDC-ready） | provider-neutral OIDC/OAuth 2.0 | verified JWT → identity mapping → Principal → ownership/tool scope |

```text
Financial Analysis Vertical Slice: COMPLETE
Transfer Vertical Slice: COMPLETE
Subscription Management Vertical Slice: COMPLETE
Durable Operation Recovery: COMPLETE
Cross-Process Financial Concurrency: COMPLETE
Transactional Outbox: COMPLETE
Durable Task Execution: COMPLETE
可信身份与多用户隔离（OIDC-ready）：COMPLETE
动态风险分级：COMPLETE
异常交易识别：COMPLETE
安全熔断：COMPLETE
受约束复杂任务规划：COMPLETE
持久化 Task DAG：COMPLETE
受约束条件节点：COMPLETE
跨场景联动：COMPLETE
中断 / Human-in-the-loop：COMPLETE
有限安全回退：COMPLETE
人工接管：COMPLETE
```

### GREEN / YELLOW / RED

比赛环境当前 Transfer Risk Policy 仅支持 CNY。非 CNY 转账 fail closed，返回稳定领域错误 `TRANSFER_RISK_CURRENCY_UNSUPPORTED`，不进行 FX，不支持外币转账。币种校验存在于 server-side deterministic policy，并在 Workflow 与 Operation 创建边界调用；即使新增 USD 付款账户，USD 同币种请求也不会获得 YELLOW / RED decision、创建 Operation、消费 Approval、创建有效 Reauthentication 或调用转账 Provider。付款账户与请求币种不一致时仍保留原有 `CURRENCY_MISMATCH` 拒绝。

| 业务风险 | 确定性规则 | 用户控制 |
|---|---|---|
| GREEN（绿色） | 纯查询 / read-only financial tools | 自动执行，无 Approval，无 Reauthentication |
| YELLOW（黄色） | 可管理订阅取消 | Approval，无 Reauthentication |
| YELLOW（黄色） | 新增模拟收款人 | 页面明确确认 |
| RED（红色） | 所有转账，无金额门槛；恢复订阅续费授权 | Approval + Reauthentication |

### Critical Banking Facts 与自然语言解释

写业务最终成功状态由 Workflow / Operation / Provider authoritative state 决定，Task `COMPLETED` 只表示该任务完成，不能代表转账或订阅取消成功。

关键金融事实逐步采用 typed structured result 向产品层暴露。账户查询的 `Task.output.account_results` 保存银行 Tool 的 `AccountListResult` / `AccountBalanceResult`，包含账户展示身份、币种、Decimal 字符串余额、后端确定性格式化的 `balance_display` 与服务器查询时间 `as_of`。账户列表最多 100 项，Task 账户结果最多 100 项；沿用 Principal ownership 和 masked number，既有 `account_id` 仅作为所属用户的资源标识。Plan 账户查询复用同一结果格式，既有分析和业务状态接口保持原有结构。

账户余额已经不再以 LLM 自由文本作为唯一产品事实源。对话中的账户卡片直接读取结构化结果，即使 assistant prose 错误地声称“余额是 1 元”，卡片仍展示 Tool 的真实余额与后端展示值；浏览器不解析 Markdown 金额，不使用 `Number()` 计算或格式化余额，也不做汇率转换。余额 Tool 读取的是 fixture balance 减成功 Provider ledger debits 的有效余额，`as_of` 表示服务器此次读取事实的时间，历史 Task 结果保留查询时快照。

产品 UI 延续 `critical fact → typed authoritative backend result`、`explanation → LLM prose` 的边界。Critical Banking Facts 包括账户身份、余额、消费分析核心金额、风险等级、Condition actual / threshold / TRUE-FALSE、Approval / Reauthentication / Workflow / Operation 状态、Provider final result、订阅当前状态，以及异常交易 rule / severity / evidence。v0.9.1 为现有结果补充确定性 display field 和只读 projection，复用已有统计、风险与状态语义，没有通用 FactEngine。

`/dashboard` 默认展示比赛 fixture 的 2026 年 8 月数据，可选择月份并刷新。对话中的消费指标卡消费 `Task.output.financial_display`；Dashboard 与月报复用同一 Financial Analytics / Report formatter。浏览器不扫描 raw transactions 汇总，不计算环比、风险或条件，不转换币种。订阅成本按币种分别展示；取消／恢复入口读取后端 `cancellable` / `resumable`。异常卡片明确“异常提示 ≠ 已确认欺诈”。

账户、消费、异常、报告和业务状态使用结构化展示，较长的解释可展开查看。收款人和订阅查询只展示正文，避免工具结果框与文字重复；后端快照继续供分析、条件及审计使用。风险卡直接读取后端 RiskDecision 的本笔、日成功、执行中、含本笔 exposure、业务日期与认证要求，不再展示旧金额阈值分级；业务时间线读取后端 Workflow presentation。`UNKNOWN` 显示“结果确认中”，不进入完成索引；Approval、Reauthentication、Task 完成均不代表业务成功。

LLM 自然语言承担解释职责，不拥有余额、金额、风险、Principal、权限或执行状态的决定权。当前没有对所有 LLM 输出进行逐句 semantic entailment 验证，也不展示隐藏推理或 Chain-of-Thought。

所有 Transfer 固定为 RED，必须 Approval 与 Reauthentication。1000 元旧阈值仅保留供历史事实兼容，不决定认证要求。日累计按 `Principal.user_id` 和 `BANKING_BUSINESS_TIMEZONE` 的自然日计算，默认时区为 `Asia/Shanghai`。执行中 exposure 包含 `CREATED / SUBMITTED / UNKNOWN` Operation，排除 `FAILED`；Provider 已成功的同一笔 Operation 不会重复计算。

订阅查询为 GREEN；订阅取消为 YELLOW，必须 Approval；恢复原套餐续费授权为 RED，必须 Approval 与 Reauthentication，本次不立即扣费。取消与恢复使用合同状态及持久动作账本，支持反复管理。

收款人在对话中列表／搜索，在 `/payees` 核对姓名、虚构银行、完整收款账号和可选别名后确认保存。转账卡提供“选择已有收款人”和“新增收款人”，新增后可返回原草稿；同名账户必须按银行与尾号选择。未匹配时等待补充，旧版无 Operation 的 `PAYEE_NOT_FOUND` 草稿可重新选择；修改收款人使原确认与强验证失效。

对话采用 `deleted_at` 软删除，未结束 Task/Plan/Workflow/Operation 会阻止删除。删除与发消息使用同一行锁；删除后禁止打开聊天和重新启动相关任务，保留业务及审计记录，切换剩余对话并清理 SSE。侧栏不显示开发身份标签和内部对话编号。

订阅分析卡只展示在总览和 Dashboard；相关回答末尾只追加一次“详细信息可在左侧「订阅与代扣总览」查看。”。仅 Provider 允许恢复的 MANAGED 合同可恢复，DETECTED_ONLY 项需联系商户。取消／恢复链接只预填请求，不构成业务确认；恢复保留未来账期，过期时按原周期推进，无账期时从恢复日起顺延一个周期。

用户可以直接输入：

```text
我有哪些账户？
工资卡余额多少？
为什么2026年8月花这么多？
分析一下工资卡2026年8月的消费
生成一份2026年8月份消费报告
我有哪些订阅？最近有没有涨价的？
取消星幕视频
恢复星幕视频订阅
我可以给哪些人转账？
从工资卡给李小雨转1元
最近有没有异常交易？
```

报告生成后可在 Conversation 中通过 ReportCard 打开，也可以从 `/reports` 查看历史报告。

## 0.10.2 转账与收款使用

| 示例 | 处理方式 |
|---|---|
| 给张三转 100 元，备注本月餐费 | 选择收款人与付款账户，核对备注，再确认、强验证和提交 |
| 明天早上 9 点从工资卡给物业转 200 元，备注房租 | 模型提取时间语义，后端规范化；部分姓名匹配由用户选择，强验证后显式授权创建预约 |
| 每月 1 号上午 9 点给物业转 100 元，共 3 次 | 展示每期日期、每期金额与总额，强验证后创建有限次周期授权 |
| 昨天聚餐 100 元，和张三、李四 AA，我也参与 | 展示 33.34、33.33、33.33 元的分摊；确认发布不扣款，其他参与者独立付款 |

预约不冻结余额，超过迟到执行窗口不无限补扣。创建时完成强验证，页面显示等待执行时间，到时重新校验后自动执行 Mock 转账。预约和周期任务在 `/scheduled-transfers` 集中管理；已取消任务可从列表移除，历史与审计保留。删除对话不会撤销已授权预约。

AA 的“自己承担”无需系统扣款；其他参与者在 `/aa` 以自己的身份选择付款账户并走既有资金操作链路。“撤回收款请求”取消对方尚未付款的请求，不重新分摊金额，保留已付款证据，提交中或 UNKNOWN 不可直接撤回。核对失败会标红对应字段并说明原因。

手机号转账当前不提供。所有新增功能均为站内 Mock，详细状态、API、配置与限制见 [智能转账指南](report/08-intelligent-transfer-guide.md)。

## 受约束任务规划

单个 Agent / Workflow 能完整完成的请求继续原路径，包括余额查询、消费分析、月度报告、独立转账、取消和恢复订阅。需要两个以上已有能力协作才进入 `COMPLEX_PLAN`。

```text
先查一下工资卡余额，再分析一下 2026 年 9 月的消费。
先看看我有哪些订阅，然后取消星幕视频。
查一下工资卡余额，如果余额不少于3000元，给张三转500元。
看看我的订阅，如果每月订阅费用不少于100元，取消星幕视频。
```

Planner 只选择 `ACCOUNT_QUERY / FINANCIAL_ANALYSIS / SUBSCRIPTION_ANALYSIS / TRANSFER_WORKFLOW / SUBSCRIPTION_CANCEL_WORKFLOW / SUBSCRIPTION_RESUME_WORKFLOW`。Proposal 不接受业务内部 ID、业务金额 payload、权限、风险或 Tool（条件 threshold 是 Decimal 字符串）；写 Workflow 始终从原始用户 Message 提取意图，沿用原有 Policy、Approval、Reauthentication、Security Guard、Operation 和 Provider。

数值条件只接受用户原始请求中明确给出的数值阈值；Planner 不能自行解释“够”“太多”“较高”等模糊表达为金额。确定性 grounding 仅匹配对应条件从句中的数值，转账等业务动作中的金额不能充当阈值。未给明确阈值时 fail closed，并提示用户提供明确金额；Planner 指定的币种也必须有原文依据，未写币种时沿用源结果的唯一币种规则。

`plans / plan_steps / plan_step_dependencies` 是固定持久化 DAG；`source_task_id` 唯一，Task retry 不再次规划。执行由原 Task worker 的 lease/attempt fence 保护，无独立 Plan worker。只读输出为 bounded structured facts；最终回答由服务器确定性整合这些事实，写步骤成功必须同时满足 Workflow 与 Operation `SUCCEEDED`。

`CONDITION` 是 Step kind，不属于 Agent Tool 或 Capability。只支持账户余额、本月支出、月度订阅成本三个预注册 `*_AT_LEAST` predicate；最多两个条件，每个能力步骤最多一个 TRUE guard。Validator 强制 source capability 匹配、source 属于依赖、guard 指向 CONDITION 且属于依赖，无条件嵌套。

`PlanConditionEvaluator` 只读取已完成 source 的 bounded output，使用现有 typed Snapshot 及 Decimal 比较。不同币种不换汇；省略币种仅允许唯一币种。Decision 保存实际值、阈值、币种、TRUE/FALSE、时间和 canonical JSON SHA-256。输入缺失/歧义或币种不合法会 FAILED，不伪装成 FALSE。

FALSE 在同一事务中将直接 guarded Step 标记 `SKIPPED / CONDITION_NOT_MET`，不创建 Workflow、Approval、Reauthentication、Operation 或 Provider 写入。其他步骤正常完成时 Plan / Task 仍 COMPLETED。TRUE 只允许进入原 Workflow，不构成 Approval、不预留余额、不保证最终资金可用；Workflow / Provider 在确认与 commit 时仍重新验证。

回退包含 CONDITION 的只读范围会清除 Decision，重新读取后计算新 hash。即使 FALSE 从未创建 Workflow，回退范围含写 Capability 仍拒绝。接管后 resume 读取已持久 Decision 和当前业务状态，不重新规划或重算已完成条件。

PlanCard 显示依赖和中文状态，关联业务继续使用原 Workflow Card。等待用户时 Step / Plan / Task 为 `WAITING_USER`；Operation 尚未收敛时为 `WAITING_EXTERNAL`。Workflow 状态事件在同一 transaction 中幂等重新调度原 Task。人工接管暂停编排并 fence 当前执行；业务卡片仍可操作，必须明确 resume 才能继续自动执行。

回退只重算目标及其下游的只读步骤，并清除旧输出、错误和时间戳；范围包含写 Capability 或 linked Workflow 时拒绝 `PLAN_ROLLBACK_NOT_SAFE`。回退不会撤销转账、恢复订阅或修改 Provider ledger。

## 架构

```text
User Message
  → Message + durable Task
  → RequestRouter
      ├─ simple request → existing Agent / Workflow
      └─ COMPLEX_PLAN → ConstrainedPlanner → PlanValidator
          → Persistent Plan DAG → TaskExecutionWorker / PlanExecutionService
              ├─ existing read-only Agent → bounded structured result
              │   → Deterministic CONDITION → TRUE → existing Workflow
              │                            → FALSE → guarded Step SKIPPED
              └─ existing Workflow → Policy → Approval → Reauthentication
                  → SecurityGuard → Operation → Provider
```


```text
OIDC Identity Provider
    → signed JWT access token → FastAPI authentication boundary
    → (issuer, subject) mapping → stable Principal.user_id
User Message
    → Message + durable Task + Event/Outbox atomic commit
    → PostgreSQL Task claim/lease + heartbeat
    → RequestRouter
    → AgentRegistry / deterministic Workflow
        ├─ MinimalBankingAgent
        ├─ FinancialAnalysisAgent → bounded TransactionAnomalySnapshot
        ├─ SubscriptionAnalysisAgent → bounded SubscriptionAnalysisSnapshot
        └─ Subscription Cancellation / Resume Workflow
    → LangGraphAgentRuntime
    → ToolRegistry → PolicyService → ToolExecutor
        ├─ transfer.commit (R4) / transfer.get_status (R1)
        └─ subscription.analyze (R1) / subscription.cancel、subscription.resume (R4)
    → TransferRiskPolicy → persisted RiskDecision
        → user advisory lock → commit-time risk re-evaluation
    → SecurityGuardService → persistent NORMAL / WRITE_LOCKED state
    → Operation
        ├─ TRANSFER
        │  → MockTransferProvider
        │  → PostgreSQL account advisory lock
        │  → authoritative balance decision
        └─ SUBSCRIPTION_CANCEL / SUBSCRIPTION_RESUME
           → MockSubscriptionProvider
           → persisted contract state + action ledger（保留旧取消事实）
    → PostgreSQL claim/lease → automatic Operation recovery
    → durable Event + Outbox intent → OutboxPublisher → EventBus/SSE
    → FinancialAnalysisSnapshot
    → SkillRegistry → MonthlySpendingReportSkill
    → immutable Report Artifact
    → Reports API
    → Structured Web UI
```

持久化职责分离：

- Alembic 管理 Conversation、Message、Task、Event 和 Report 等应用表。
- LangGraph PostgreSQL Checkpointer 管理 Agent runtime checkpoint。
- committed Mock Bank synthetic data 作为基线 fixture；工资卡等有效余额会减去持久化 provider ledger 中已成功的转出，不修改 committed JSON。
- Mock Provider 在自己的短 PostgreSQL transaction 内按 source account 串行化，重新计算 fixture balance 减成功 ledger 的 authoritative balance，然后原子地接受或拒绝转账。
- Operation recovery 调度、尝试次数和 lease 同样持久化在 Application PostgreSQL；LangGraph checkpoint 不是 Workflow/Operation 业务事实源。
- Task 的调度、attempt、lease 和 fencing token 持久化在 Application PostgreSQL；LangGraph checkpoint 只保存 Agent runtime 进度，不代替 Task ownership。
- 外部 `(issuer, subject)` 只在认证边界映射到稳定的内部 `user_id`；Conversation、Task、Report、Workflow、Approval、Reauthentication、Operation 和银行数据均以该内部身份做 ownership scope。
- HTTP credential 不进入 Task、Message、Event、Outbox、Prompt 或 LangGraph checkpoint。Task worker 只从 Task 与 Conversation 的 authoritative `user_id` 构造 server-side execution Principal。
- 所有需实时通知的 durable Event 都与唯一 Outbox intent 在同一业务 transaction 内写入；Outbox 只引用 Event identity，不复制 payload。
- `security_guard_states` 保存当前 Principal 的熔断计数与期限；安全 signal 通过现有 Event + Outbox 留痕，不保存验证码、JWT 或隐藏推理。

产品 Runtime 是 `LangGraphAgentRuntime`。`ManualAgentRuntime` 仅作为 reference 保留，不承载新功能。

## 设计基线：新增功能前必读

[Architecture Baseline v0.1](docs/architecture-baseline-v0.1.md) 定义了本项目长期遵守的 Agent Engineering 方向。它不是过期的实现清单，而是防止功能演进偏离整体设计的架构基线。

核心原则包括：

- Workflow First, Agent Second：能确定性完成的业务不强行 Agent 化。
- LLM ≠ Business System：LLM 负责理解与选择，业务系统负责事实和执行。
- Structured State > Conversation：业务事实进入结构化状态，不依赖聊天文本。
- Default Deny 与 Least Privilege：Agent、Skill、Workflow、Tool 只获得最小必要权限。
- Domain API > Agent API：前端面向 Banking Application，不直接耦合 Agent Runtime。
- Structured handoff：组件之间传 typed result，不传隐藏推理或 Chain-of-Thought。
- Modular Monolith First：在真实扩展问题出现前不引入不必要的分布式复杂度。

新增功能在实现前必须先判断它属于哪一类执行概念：

| 概念 | 负责的问题 |
|---|---|
| Agent | 现在应该做什么？ |
| Skill | 这类任务怎样专业、稳定地完成？ |
| Workflow | 这件事必须按照什么状态和规则完成？ |
| Tool | 系统具体能够做什么？ |

设计评审至少检查：确定性逻辑是否误放进 LLM、状态是否结构化、权限是否最小、是否绕过 Policy/Registry/Domain API，以及是否为了技术展示引入尚未需要的 Planner、RAG、MCP 或 Multi-Agent。

当前实现按该基线渐进建设，并不代表基线中所有未来组件已经实现。若新需求需要改变基线原则或执行边界，应先更新设计文档并记录偏差与理由，再修改代码，不能静默偏离。

## 可信金融数据边界

- 金额统一使用 `Decimal`，禁止使用 `float` 进行金融计算。
- 月份使用 `YYYY-MM`，范围为自然月左闭右开区间。
- 有效交易 status 显式为 `POSTED`。
- Spending 是 `POSTED + DEBIT + category != TRANSFER`。
- Income 是 `POSTED + CREDIT + category != TRANSFER`。
- 不做汇率换算；同次聚合出现多币种时返回 `MIXED_CURRENCY_UNSUPPORTED`。
- Financial Tools 只返回聚合结果或 bounded Top N，不向 LLM 提供整月 raw transaction history。
- 异常规则固定为 `AMOUNT_SPIKE`、`RAPID_DUPLICATE`、`NEW_MERCHANT_HIGH_AMOUNT`、`SUBSCRIPTION_PRICE_SPIKE`；金额与比例只用 `Decimal`，baseline 按 Principal + currency 隔离。
- **异常提示 ≠ 已确认欺诈。**
- **异常交易检测结果不会自动触发 Security Write Lock。熔断由明确的安全执行失败信号触发。**
- Report exact Decimal 在 JSON 中序列化为 string；前端直接使用 Backend `*_display`，不重新计算或四舍五入。

> Financial Agents should receive deterministic summaries by default, not full transaction history.

## 权限边界

默认仍是只读和最小权限。静态 Tool 权限等级回答“谁可以调用该能力”；GREEN / YELLOW / RED 业务风险等级回答“当前这一笔请求需要哪些用户控制”。两者独立，业务风险不会扩大 Agent 的 Tool authority。

- 所有业务 API 都通过统一 `get_current_principal()` 认证；缺失/无效 credential 返回 401，未 provision 的合法外部身份返回 `403 IDENTITY_NOT_PROVISIONED`。
- detail、action 和 SSE 在查询层按 `Principal.user_id` 限定，跨用户 UUID 访问统一表现为 404；list 查询直接在 repository 层按用户过滤。
- LLM、Tool arguments、request body 和浏览器都不能提供或切换 authority。ToolExecutionContext 只能接收 server-created Principal，账户、收款人、余额和交易分析从该 Principal 获得 user scope。

- `agent:minimal-banking`：允许 `account.list`、`account.get_balance`、`payee.list`、`payee.search`；没有收款人保存或转账权限。
- `agent:financial-analysis`：允许 `account.list`、四个 Financial Tools 和 `transaction.detect_anomalies`，不允许余额、转账、卡片或其他写能力。
- `agent:subscription-analysis`：只允许 `subscription.analyze`，不允许 `subscription.cancel` / `subscription.resume` 或 Operation/Approval 写入。
- `skill:monthly-spending-report`：`allowed_tools=[]`，只能消费 `FinancialAnalysisSnapshot`。
- `workflow:transfer`：允许三项 R1 读能力，以及仅接受持久化 `operation_id` 的 `transfer.commit` (`R4_FINANCIAL_COMMIT`) 和 `transfer.get_status` (R1)。
- 订阅取消／恢复确定性 Workflow：允许有界订阅读取、对应的 `subscription.cancel` / `subscription.resume` 和状态查询。取消与恢复共享内部注册 caller，Planner／Task 路由分别使用 `workflow:subscription-cancel` / `workflow:subscription-resume`。写 Tool 只接受持久化 `operation_id`。
- Recovery worker 不是新的 Tool caller，也不扩大 `transfer.commit` allowlist；它只能 claim 已有 Operation，并调用与手工 reconcile 相同的 `OperationService` 状态转移。
- 任何 Agent 或 Skill 都看不到、也无权调用 `transfer.commit`；LLM 在意图提取后完全退出执行路径。
- Reports API 只有 GET list/detail，没有 POST、PUT、PATCH 或 DELETE。

Router 只选择 Agent/Workflow 和 requested output，不扩大权限。未知 Tool、越权调用和写操作请求均 fail closed。

## 快速启动

准备配置；认证模式必须显式指定，不存在缺省到 development principal 的 fallback：

```bash
cp .env.example .env
```

至少填写 OpenAI-compatible Provider：

```env
LLM_PROVIDER=openai_compatible
LLM_BASE_URL=https://example.com/v1
LLM_API_KEY=
LLM_MODEL=
```

`LLM_BASE_URL` 必须是 API root，Adapter 会追加 `/chat/completions`。密钥不会进入数据库、Event、Prompt trace 或前端。

本地开发可显式使用固定 Principal：

```env
APP_ENVIRONMENT=development
AUTH_MODE=development
DEVELOPMENT_USER_ID=dev-user-001
NEXT_PUBLIC_AUTH_MODE=development
```

OIDC 模式验证标准 JWT signature、`iss`、`aud`、`exp`、可选 `nbf`、`sub`、allowed algorithm 和 `kid`/JWKS。`OIDC_JWKS_URL` 留空时使用标准 discovery；生产环境禁止 `AUTH_MODE=development`。当前比赛能力为 OIDC-ready 的认证边界和多用户隔离，未接入真实生产 IdP。

```env
APP_ENVIRONMENT=production
AUTH_MODE=oidc
OIDC_ISSUER=https://idp.example.com
OIDC_AUDIENCE=banking-api
OIDC_JWKS_URL=
OIDC_ALLOWED_ALGORITHMS=["RS256"]
NEXT_PUBLIC_AUTH_MODE=oidc
NEXT_PUBLIC_OIDC_AUTHORITY=https://idp.example.com
NEXT_PUBLIC_OIDC_CLIENT_ID=banking-web
NEXT_PUBLIC_OIDC_SCOPE="openid profile"
```

转账日累计使用明确的业务时区：

```env
BANKING_BUSINESS_TIMEZONE=Asia/Shanghai
```

前端使用 Authorization Code + PKCE；access token 仅由成熟 OIDC client 保存在内存中并通过 Bearer header 发送，SSE 使用 authenticated fetch streaming，不把 token 放入 URL。外部身份必须显式 provision，系统不会按 email/display name 猜测或自动继承 demo 银行数据：

```bash
cd apps/api
uv run python -m banking_api.security.authentication.provision \
  --user-id dev-user-001 \
  --issuer https://idp.example.com \
  --subject external-subject
```

启动完整产品：

```bash
docker compose up --build
```

- Web：<http://localhost:3000>
- Dashboard：<http://localhost:3000/dashboard>
- Reports：<http://localhost:3000/reports>
- 订阅与代扣总览：<http://localhost:3000/subscriptions>
- 收款人管理：<http://localhost:3000/payees>
- API：<http://localhost:8000>
- OpenAPI：<http://localhost:8000/docs>

API 启动时依次执行 Alembic migration、LangGraph checkpoint setup、legacy stale Task 调度修复，然后启动 Task execution、Operation recovery 和 Outbox publication 三个专用 loop。关闭时三个 worker 都会停止并等待当前工作收敛。HTTP message handler 只持久化 Message/Task/Event/Outbox 并返回，不再拥有 Task 生命周期。

Task worker 通过环境变量配置：

```env
TASK_WORKER_ENABLED=true
TASK_WORKER_POLL_INTERVAL_SECONDS=0.5
TASK_WORKER_LEASE_SECONDS=60
TASK_WORKER_HEARTBEAT_SECONDS=15
TASK_WORKER_INITIAL_RETRY_SECONDS=2
TASK_WORKER_MAX_RETRY_SECONDS=120
TASK_WORKER_BACKOFF_MULTIPLIER=2
TASK_WORKER_BATCH_SIZE=4
TASK_WORKER_MAX_CONCURRENCY=4
```

`TASK_WORKER_HEARTBEAT_SECONDS` 必须小于 lease duration。batch 不超过本地 concurrency 上限，claim 后立即并发 dispatch，避免长 LLM Task 在队列尾部耗尽 lease。

Recovery 通过环境变量配置：

```env
OPERATION_RECOVERY_ENABLED=true
OPERATION_RECOVERY_POLL_INTERVAL_SECONDS=5
OPERATION_RECOVERY_LEASE_SECONDS=60
OPERATION_RECOVERY_INITIAL_RETRY_SECONDS=5
OPERATION_RECOVERY_MAX_RETRY_SECONDS=300
OPERATION_RECOVERY_BACKOFF_MULTIPLIER=2
OPERATION_RECOVERY_BATCH_SIZE=10
```

Outbox 通过环境变量配置：

```env
OUTBOX_PUBLISHER_ENABLED=true
OUTBOX_PUBLISHER_POLL_INTERVAL_SECONDS=0.5
OUTBOX_PUBLISHER_LEASE_SECONDS=30
OUTBOX_PUBLISHER_INITIAL_RETRY_SECONDS=1
OUTBOX_PUBLISHER_MAX_RETRY_SECONDS=60
OUTBOX_PUBLISHER_BACKOFF_MULTIPLIER=2
OUTBOX_PUBLISHER_BATCH_SIZE=20
```

## 本地开发

Backend：

```bash
cd apps/api
uv sync
uv run alembic upgrade head
uv run uvicorn banking_api.main:app --reload
```

Frontend：

```bash
pnpm install
pnpm web:dev
```

常用验证：

```bash
cd apps/api
uv run ruff check . ../../scripts
uv run pytest
```

```bash
pnpm api:generate
pnpm web:lint
pnpm web:typecheck
pnpm --filter @banking/web test
pnpm web:build
```

PostgreSQL integration 必须使用库名包含 `test` 的隔离数据库：

```bash
cd apps/api
TEST_DATABASE_URL=postgresql+asyncpg://banking:banking@localhost:5432/banking_release_v093_test \
  uv run pytest -m postgres
```

真实 LLM 与 synthetic 数据的完整报告链路 smoke（先为隔离库执行 migration）：

```bash
APP_ENVIRONMENT=test AUTH_MODE=development \
DATABASE_URL=postgresql+asyncpg://banking:banking@localhost:5432/banking_test \
LANGGRAPH_CHECKPOINT_DATABASE_URL=postgresql://banking:banking@localhost:5432/banking_test \
  uv run --project apps/api python scripts/smoke_report_product.py
```

Smoke 验证 Router、Financial Agent、确定性工具、Skill、Report persistence、GET API、Golden core 和单一用户确认消息；不会输出 API Key 或 Chain-of-Thought。

## Audit Evidence 与安全模型

对话 Task 的“查看审计链”读取 `GET /api/v1/tasks/{task_id}/audit`，按数据库 Event.sequence 展示结构化决定、用户动作与资源关联，技术详情可查看 payload hash、exposure、Condition source hash 和 Provider reference。历史 Event 与当前资源快照分别展示，UNKNOWN 和风险升级不会被最终成功覆盖；旧版本未记录的细节不补造，超出 1000 Event 明确提示不完整。

Audit 不复制完整 Prompt、不展示 LLM 隐藏推理/Chain-of-Thought、JWT、API key 或 OTP；Reauthentication 明确标注 Mock。应用 Event append-only 不等于数据库防篡改，dev/test reset 会清理该用户证据。详细安全自评和 Threat Model 见当前 Implementation Report。

Prompt Injection 即使影响自然语言，也不能扩大 server Principal、Tool allowlist、Risk Policy、Approval/reauth、Workflow、Operation 或 Provider 的 authority。关键金融事实由 typed backend result 提供，写成功仍要求 Workflow + Operation 同为 SUCCEEDED。没有逐句 semantic entailment verifier。

转账意图在共用后端提取边界严格规范 CNY/RMB/人民币/元/¥/￥；必须有原始消息表达或既有明确缺省规则，未知/矛盾表达不盲目转 CNY。非 CNY 仍由现有校验与 CNY-only Risk Policy fail closed。

## 比赛前唯一推荐 prepare 流程

1. 停止连接 Demo 库的 API/Web、Task、recovery、Outbox workers。
2. 执行下节 owner-scoped reset，保留 migration/checkpoint schema。
3. 启动 Docker product。dev/test 可显式使用 `DEMO_REFERENCE_TIME=2026-09-28T12:00:00Z docker compose up --build -d` 固定 synthetic 异常/续费窗口；生产禁止覆盖，默认真实时间。Risk business date、Approval/reauth TTL、Guard、Task lease、recovery 始终真实时间。
4. 仓库根运行 `uv run --project apps/api python scripts/demo_preflight.py`；全部 PASS 后继续。脚本只读，API/Web 默认为 localhost:8000/3000，不打印密钥/OTP。
5. 用另一隔离测试库运行 required smoke；停止该测试库的 worker 后执行 report product + stability，之后才启动该测试库 API 做 plan/audit/security HTTP smoke，避免多个 runner 抢同一 Task。不要将 smoke 指向真实业务环境。
6. 开始 presentation；结束后再次 reset。

报告稳定性至少 10 次（真实 LLM，有费用/延迟），不放宽 validator：

```bash
APP_ENVIRONMENT=test AUTH_MODE=development \
DATABASE_URL=postgresql+asyncpg://banking:banking@localhost:5432/banking_smoke_v093_test \
LANGGRAPH_CHECKPOINT_DATABASE_URL=postgresql://banking:banking@localhost:5432/banking_smoke_v093_test \
  uv run --project apps/api python scripts/smoke_report_stability.py --runs 10
```

上述隔离库须先 migration；真实 LLM 会接收必要 synthetic 查询/汇总。确保已授权当前配置的 LLM 目的地。脚本输出 successes / validation failures / golden mismatches / other failures，任何失败返回非零。

已有 Plan HTTP smoke 配置保持有效。针对同一隔离 API（开发/测试、Mock Provider）新增：

```bash
AUDIT_SMOKE_BASE_URL=http://127.0.0.1:8001 \
  uv run --project apps/api python scripts/smoke_audit_product.py
SECURITY_SMOKE_BASE_URL=http://127.0.0.1:8001 \
  uv run --project apps/api python scripts/smoke_security_product.py
```

Audit smoke 显式确认、完成 Mock 强验证并提交一次 synthetic RED 转账，核对完整链和 secret exclusion；security smoke 发送绕过确认的请求并直接尝试 commit，必须拒绝且零 Operation/Provider write。v0.9.2 历史记录中四项真实模型产品 smoke 通过，固定报告场景重复 10 次均成功；v0.9.3 未重新执行这组真实模型和稳定性检查。这是有限测试窗口的证据，不保证任意输入或未来模型永远稳定。

## 比赛 Demo reset

只允许 `APP_ENVIRONMENT=development/test`，production 在连接数据库前拒绝。脚本不注册为业务 API 或 LLM Tool。先停止所有连接该 Demo 数据库的 API、Task、Operation recovery、Outbox worker，再执行显式用户范围清理：

```bash
docker compose stop api web
APP_ENVIRONMENT=development AUTH_MODE=development \
DATABASE_URL=postgresql+asyncpg://banking:banking@localhost:5432/banking \
LANGGRAPH_CHECKPOINT_DATABASE_URL=postgresql://banking:banking@localhost:5432/banking \
  uv run --project apps/api python scripts/reset_demo_state.py \
  --user-id dev-user-001 --workers-stopped
docker compose start api web
```

reset 清除指定用户的新增收款人、订阅状态／动作及旧取消账本、Mock transfer ledger、Security Guard、Workflow、Approval、Reauthentication、Operation、Plan、Task、Report、Conversation、Message、Event/Outbox，以及对应 Task/Plan attempt 的 LangGraph checkpoint。保留其他用户、identity mapping、Alembic/checkpoint migration 和表结构；不删除数据库或 volume。应用与 checkpoint 必须在同一数据库，以保持事务内清理；存在未过期执行/发布 lease 时拒绝，停止 worker 后等待 lease 到期再重试。

成功后工资卡恢复 `¥23,864.52`，当日 exposure 为零，星幕视频恢复 ACTIVE；重复 reset 不产生新状态。浏览器刷新后开始新演示。RED 的模拟验证码由本地 `MOCK_REAUTH_CODE` 决定，不是真实短信；示例配置使用 `change-me-for-local-development`。

建议依次演示：账户 → 2026-08 Dashboard/报告 → 收款人查询／新增 → 1 元 RED 转账（确认＋强验证）→ 订阅取消／恢复（恢复本次不扣款）→ Condition TRUE/FALSE → 对话删除及活动流程拦截 → UNKNOWN recovery → 最后 Security Guard。结束后 reset 恢复初始状态。

## 主要 API 与页面

```text
GET  /api/v1/dashboard?month=2026-08
GET  /api/v1/conversations
POST /api/v1/conversations
GET  /api/v1/conversations/{conversation_id}
DELETE /api/v1/conversations/{conversation_id}
POST /api/v1/conversations/{conversation_id}/messages
GET  /api/v1/payees?query=...&offset=...
POST /api/v1/payees   # 核对后 confirmed=true；输入完整收款账号，后续仅显示尾号
PATCH /api/v1/payees/{payee_id}
DELETE /api/v1/payees/{payee_id}
GET  /api/v1/tasks/{task_id}
GET  /api/v1/tasks/{task_id}/events
GET  /api/v1/tasks/{task_id}/audit
GET  /api/v1/demo/readiness   # dev/test only; read-only; production 404
GET  /api/v1/reports
GET  /api/v1/reports/{report_id}
GET  /api/v1/subscriptions
GET  /api/v1/subscriptions/{subscription_id}
GET  /api/v1/security/status
GET  /api/v1/plans?conversation_id=...
GET  /api/v1/plans/{plan_id}
POST /api/v1/plans/{plan_id}/actions/take-over
POST /api/v1/plans/{plan_id}/actions/resume
POST /api/v1/plans/{plan_id}/actions/rollback
GET  /api/v1/workflows/{workflow_id}
GET  /api/v1/workflows?conversation_id=...
POST /api/v1/workflows/{workflow_id}/actions/{set-recipient-query|select-payee|select-source-account|set-amount|select-subscription|set-remark|set-execution-time|approve|start-reauth|verify-reauth|commit|cancel}
GET  /api/v1/scheduled-transfers
GET  /api/v1/scheduled-transfers/{schedule_id}
POST /api/v1/scheduled-transfers/{schedule_id}/actions/{authorize|cancel|cancel-series|delete}
GET  /api/v1/aa-requests
GET  /api/v1/aa-requests/{request_id}
PATCH /api/v1/aa-requests/{request_id}
POST /api/v1/aa-requests/{request_id}/actions/publish
GET  /api/v1/aa-accounts
POST /api/v1/aa-shares/{share_id}/actions/{pay|reject|cancel}
GET  /api/v1/operations/{operation_id}
POST /api/v1/operations/{operation_id}/actions/reconcile
```

```text
/                    Conversation Workspace
/dashboard           Authoritative financial/account overview
/reports             Report history
/reports/{reportId}  Structured monthly report
/subscriptions       Subscription overview and cancellation/resume entry
/payees              Persistent simulated payee management
/scheduled-transfers Single and monthly scheduled transfer management
/aa                  Mock AA participant requests and payments
```

SSE 用于实时通知；Task、Report 和 Workflow API 始终是页面刷新恢复的 authoritative source。`business state + Event + Outbox intent` 在同一 PostgreSQL transaction 内提交；Outbox Publisher 使用 `SKIP LOCKED` + durable lease 向现有 EventBus 做 at-least-once 发布。发布成功后、`published_at` 写回前崩溃可能导致重复通知，但不会重复业务副作用。

SSE connection 本身同样要求认证并先验证 Conversation ownership。OIDC 模式下浏览器通过 streaming `fetch` 在 `Authorization` header 携带 access token，不使用 query-string token。

`READY_FOR_COMMIT` 表示当前 payload 已审批并满足所需控制。所有转账和恢复订阅授权均为 RED，必须有效 Reauthentication；取消订阅为 YELLOW，仅需确认。提交前再次检查风险、业务资料、授权 hash、版本及 TTL。旧黄色转账草稿按 RED 展示，若仍缺少强验证，提交只会转入 `REAUTH_REQUIRED`，不会创建新 Operation。已提交的历史操作保留原风险事实。

Commit 的 user risk advisory lock 只覆盖“重读 exposure → 风险评估 → 授权校验 → Operation 创建 → 事务提交”，不覆盖 Provider I/O。它串行校验用户当前风险、日累计信息和授权状态；Mock Provider 的 account lock 保护账户余额，两者彼此独立。`SUBMITTED` 不是成功；`UNKNOWN` 只能查询原 Operation，不得新建或换 key 重提。只有 Workflow 与 Operation 同时 `SUCCEEDED` 才能展示“转账成功”。

`CREATED / SUBMITTED / UNKNOWN` 会按持久化 `next_reconcile_at` 自动恢复。多个 API process 可各自运行 worker；PostgreSQL `FOR UPDATE SKIP LOCKED` 与有期 lease 保证同一 Operation 在有效 lease 内只有一个 claim。Provider/network I/O 不持有数据库行锁。

Task 执行同样使用 PostgreSQL `FOR UPDATE SKIP LOCKED`、持久 lease、attempt fencing 和 heartbeat。保证是“at-least-once execution attempt + fenced authoritative completion”，不是外部副作用 exactly-once。Report 依赖 `source_task_id` 唯一约束；Plan retry 复用同一 DAG，写步骤 retry 通过 source_task_id 找回同一 Workflow（包括 Workflow 已创建但尚未保存 link 的 crash window）。Transfer retry 复用同一 Workflow，金融副作用仍只由 Operation/Provider/OperationRecoveryWorker 收敛。

Idempotency 和资金并发是两个独立 invariant：同一 idempotency key 通过 provider ledger unique constraint 仅执行一次；不同 Operation/key 通过 source-account-scoped PostgreSQL transaction advisory lock 不能并发花穿余额。Workflow balance check 仅用于 early validation，Provider commit-time balance check 才是最终资金 correctness boundary。

`WRITE_LOCKED` 只阻止新的 Transfer / Subscription cancel Operation 以及 reauthentication start/verify；GREEN 查询、异常分析和状态查询继续可用。Operation 创建前服务端 fail closed，因 lock 拒绝时不消费 Approval、不创建 Operation、不调用 Provider。`locked_until` 到期后 lazy clear，无后台 unlock worker。

已有 Operation 的 commit retry 在取得 Security Guard user lock 后先返回原记录，即使客户端使用创建前版本且用户随后 WRITE_LOCKED，也不重消费 Approval 或换 idempotency key。CREATED / SUBMITTED / UNKNOWN 继续由原 Recovery 收敛，不重新检查用户写锁。

Security Guard 状态转移与新 Operation 创建共享同一个 Principal-scoped PostgreSQL transaction advisory lock。Authoritative write gate 与 Operation/Approval/Workflow 更新在同一 transaction 中，因此 lock activation 与 Operation creation 对同一用户有唯一线性化顺序。Transfer 的全局锁顺序固定为 `Security Guard user lock → Transfer Risk user lock`；订阅取消／恢复在应用提交边界获取前者；Provider 另外用用户＋合同的锁和版本串行更新状态。

## 项目结构

```text
apps/api/                 FastAPI、LangGraph runtime、domain、persistence、tests
apps/web/                 Next.js Dashboard、Conversation、Reports、Subscription、Payees UI
packages/api-client/      OpenAPI 生成的 TypeScript schema
scripts/                  Golden generation 与 smoke scripts
docs/                     版本交付、测试结果与设计记录
```

## 当前交付文档

- [v0.10.2 更新说明](docs/release-notes-v0.10.2.md)
- [智能转账、备注、预约与 AA 指南](report/08-intelligent-transfer-guide.md)
- [转账扩展实际验证记录](report/09-transfer-extensions-validation.md)

以下是保留的历史 v0.9.3 交付文档：

- [Implementation Report v0.9.3](docs/implementation-report-v0.9.3.md)
- [Repository Tree v0.9.3](docs/repository-tree-v0.9.3.md)
- [Test Results v0.9.3](docs/test-results-v0.9.3.md)

具体浏览器反馈、截图和本地更新记录见 [管理功能修复与验收](docs/banking-management-repairs.md)。历史版本文档保留在 `docs/`，其中旧黄色转账规则不代表当前规则。

### 升级到 v0.10.2

数据库目标为 `0030`。从现有库升级时先备份并暂停新业务写入，运行 `alembic upgrade head`，同步更新 API/Web；不要清库或重置账本。迁移 `0028` 移除手机号转账业务，保留历史操作恢复；`0029` 添加有限次按月授权和期次关联；`0030` 添加已取消预约列表软删除标记。更早的备注、预约、AA 和管理表迁移随 Alembic 链自动执行。

预约需要 `MOCK_SCHEDULED_TRANSFERS_ENABLED=true`，仅允许 Mock Provider。默认单次最少提前 60 秒、最长 30 天、迟到窗口 300 秒；按月最多 12 次、跨度最多 366 天，分别由 `RECURRING_TRANSFER_MAX_OCCURRENCES` 与 `RECURRING_TRANSFER_MAX_DAYS` 控制。即时 Approval 600 秒与强验证 300 秒不延长；预约转换为仅适用于固定内容与执行窗口的一次性授权。

### 历史：升级到 v0.9.3

从 0017 升级需要迁移 `0018_banking_management.py`，添加对话删除标记、收款人、订阅状态／动作账本和恢复操作枚举，并回填旧成功取消状态。先暂停新业务写请求，让已有 CREATED／SUBMITTED／UNKNOWN Operation 收敛，再备份、迁移并同步更新 API/Web；不要为升级重置业务数据。已有管理记录时迁移降级会拒绝执行，避免丢失数据。新建环境可使用上面的 `docker compose up --build`，容器启动自动运行迁移。

## 当前限制

Dashboard 是复用既有服务的只读 projection，各服务读取有界快照，不提供跨服务原子快照。对话分析只展示实际完成的工具结果，未查询的 Top transactions 不由浏览器补算。LLM 路由、意图提取与报告说明可能失败；后端会保持既有校验并明确拒绝，用户可重试，不保证模型每次解释正确。历史 Task 是查询时快照，实时余额应重新查询或刷新 Dashboard。

Plan 最多 8 步、2 个 CONDITION、一个写 Workflow，按 ordinal 顺序执行 ready steps；条件只有预注册 Predicate，不支持 ELSE、nested conditions、任意表达式、AND/OR、loops、多写 Workflow、动态重规划或自由 Agent 协商。复杂请求中的月度 Report Artifact 暂未作为 Plan Capability 注册，会整体拒绝；独立分析并生成报告仍走完整 Financial vertical slice。没有 Plan cancel API，业务取消沿用 Workflow。


当前写入仅限比赛 synthetic banking environment 中的持久化 `MockTransferProvider` 和正式 `MockSubscriptionProvider`；未连接真实商户订阅 API。RED 强验证使用 `MockReauthenticationProvider`。

订阅检测当前只支持固定的月度/年度 cadence 窗口和 fixture alias；不做 FX、不根据商户类型主观判断“重复”，不推断用户是否真正使用某项订阅。订阅消息 Worker 每 30 秒检查账期：提前 7 天一次站内提醒；可管理合同模拟自动扣费后一次结果提醒（余额不足或安全锁定时提醒失败，不扣款）。首次启用不补扣旧账期、不推送已有历史流水；停机后按持久扫描进度恢复。每个账期和事件持久去重，已读或删除后不会重复生成。`MOCK_SUBSCRIPTION_BILLING_ENABLED` 仅可在 development/test 开启，示例合同绑定工资卡；DETECTED_ONLY 只提示预计日期，不自动扣费。

异常检测只是可解释的确定性分析，不是完整 Fraud Detection Platform；不做 FX、主动通知、Fraud ML、通用 Rule Engine/DSL 或人工审核台。Security Guard 只有 `NORMAL / WRITE_LOCKED`，本版无管理员手工解锁。

登录 Authentication 只回答“是谁”，不替代 canonical payload Approval，也不替代 RED 在 commit 前要求的 Reauthentication。

仍然没有 balance reservation/hold/capture 系统。TaskExecutionWorker、ScheduleWorker、OperationRecoveryWorker 和 OutboxPublisher 是明确、独立的专用 loop，不是 Celery、Redis、Kafka、通用任务队列或 Generic Worker/Scheduler Framework。Task worker 仍由 API process 托管，未提供独立 worker deployment、优先级队列或 per-conversation ordering。

EventBus 仍是 process-local：多 API process 下，某个 publisher 的本地发布不保证另一 process 上的 SSE client 收到。本版也没有 client acknowledgement、SSE replay、Outbox DLQ、archival/cleanup、分布式 metrics/tracing 或跨进程 realtime broker；Resource API 仍是事实源。

真实 HTTP + 当前 LLM 的 Plan smoke 使用独立 synthetic 数据库和最新 API：

```bash
# 单独终端启动隔离 API，先为 banking_test 执行 migration
APP_ENVIRONMENT=test AUTH_MODE=development \
DATABASE_URL=postgresql+asyncpg://banking:banking@localhost:5432/banking_test \
LANGGRAPH_CHECKPOINT_DATABASE_URL=postgresql://banking:banking@localhost:5432/banking_test \
  uv run --project apps/api uvicorn banking_api.main:app --host 127.0.0.1 --port 8001
```

```bash
APP_ENVIRONMENT=test AUTH_MODE=development \
PLAN_SMOKE_BASE_URL=http://127.0.0.1:8001 \
  uv run --project apps/api python scripts/smoke_plan_product.py
```

该脚本完成只读 DAG，以及一次明确 Approval + commit 的 synthetic 订阅取消，并核对原 Operation 幂等复用；不要指向真实业务环境。完成后停止临时 API。report smoke 自行运行 TaskRunner，不与该测试库的 API worker 并行；PostgreSQL fixture tests 也不能与该库 worker 同时运行。

订阅管理页面支持直接取消：点击「取消订阅」，在页面内弹窗确认后调用 `POST /api/v1/subscriptions/{id}/cancel`，持久化取消状态并刷新费用汇总，不再跳转到对话。请求需要明确确认、合同版本和幂等键；接口校验当前用户归属、安全写锁和可取消性，沿用 Mock Provider 的合同锁与动作账本，取消后自动扣费执行器不再生成后续扣费。该接口不提供给 Agent 工具；对话中的订阅取消／恢复仍走原 Workflow。其他页面的取消／恢复链接只预填一次，工作台读取后移除 URL 的 cancel／resume 参数。新建对话不会再次带入。最近对话右侧「编辑」保存名称，手动名称不会被自动命名覆盖。
