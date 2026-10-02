# AI Banking Agent：核心算法说明

版本：**v0.8.2**。核对日期：**2026-10-02**。

核心是“受限 LLM 决策 + 确定性金融计算 + 状态机 + 数据库并发与恢复协议”。没有训练自有模型、强化学习策略、Fraud ML 或向量检索。本文描述当前代码，不把未来设想当作已实现。

配套：[网页测试与版本演进](learning-guide-v0.8.2.md) · [系统架构图](system-architecture-v0.8.2.md)。源码路径默认相对于 `apps/api/src/banking_api/`。

## 1. 路由与受限 Agent Loop

**输入：**原始 Message、有限上下文、服务器 Principal。**输出：**执行者、工具事实与答复。

Router 让 LLM 返回严格 JSON，Pydantic 检查 route/requested_output/confidence/额外字段，最多一次格式重试。确定性规则再把条件请求归入 COMPLEX_PLAN，检查多能力与不支持的复杂报告路径。分类不赋予权限。

Agent 使用两个 LangGraph 节点：

```text
LLM 节点
  ├─ final → 结束
  ├─ fatal error → 失败
  └─ tool calls → Tool 节点 → 结构化结果 → LLM 节点
```

ContextBuilder 只给当前指令/请求、最近有限 USER/ASSISTANT 消息、允许的工具 schema 与本次工具结果。默认最多6次 LLM step、4次 Tool call；Router/Planner 是独立调用。

每个调用：注册表查找 → Policy 鉴权 → 输入 schema → handler → 输出 schema。需要可信身份、正确 caller、Capability allowlist、匹配 risk/side_effect。未知工具、越权、输出/执行错误终止；参数 schema 错误可在预算内反馈模型修正。

账户 Agent 可查账户/余额；消费 Agent 可查账户列表、四项消费统计与异常；订阅 Agent 只有 subscription.analyze。两个写 Tool 仅允许对应 Workflow。LLM 不决定 graph edge、Principal 或权限。

例：“工资卡余额多少？”通常 list_accounts → get_balance → final，内部 ID 来自工具。源码：`routing/request_router.py`、`runtime/langgraph/graph.py`、`context/builder.py`、`tools/executor.py`、`policy/service.py`。

## 2. 确定性消费统计

**输入：**用户范围内固定交易、月份、可选账户。**输出：**汇总、分类、环比、Top N。

月份使用 UTC 自然月左闭右开区间；金额字符串转 Decimal；有效状态只接受 POSTED，同次聚合不混币种、不换汇。

```text
消费 S = POSTED 且 DEBIT 且 category != TRANSFER
收入 I = POSTED 且 CREDIT 且 category != TRANSFER
total_spending = Σ amount(t), t ∈ S
total_income = Σ amount(t), t ∈ I
category_share = category_amount / total_spending
absolute_change = current - previous
percentage_change = (current - previous) / previous × 100
```

上期为零时百分数为 null，不是无限或100%。比例使用 Decimal precision 28。分类按金额降序/category升序；Top N 按金额降序/时间升序/交易ID升序，最多20条。不向 LLM 传整月流水。

八月：16547.30−9333.20=7214.10；环比 exact 为77.29503278618265975228217546%，报告展示+77.3%。工资卡 scope 八月为7657.30。

扫描分组 O(n)，排序 O(n log n)，当前为小规模 fixture 内存计算。源码：`financial/analytics_service.py`。

## 3. 报告生成与事实约束

**输入：**成功工具结果构造的 FinancialAnalysisSnapshot。**输出：**不可变报告 Artifact。

1. 校验月份/scope/币种、summary与breakdown一致，以及 required tool evidence；核心不全在模型调用前拒绝。
2. Python 生成 numeric core 并保留排序；Formatter 用 ROUND_HALF_UP 生成两位金额、一位百分数等展示字段。
3. LLM 在 tools=[] 下仅生成标题与2–5条洞察，每条必须引用已有 evidence_refs。
4. 校验 JSON schema、引用、未知 category/account token、正文数字泄漏（阿拉伯/全角/中文数字及常见英文数词）；最多一次修正。
5. 合并保留数值核心，保存完整 content_json、快照hash、Skill/Report版本。唯一键 `(source_task_id, report_type, report_version)` 防同一 Task 重复 Artifact。

summary与breakdown必需；comparison/Top N缺失时 PARTIAL。报告 GET 不重新生成。报告前端用后端 display字段；转账/订阅/异常卡片仍有 Number() 参与展示格式化，不参与后端金额计算、阈值和授权判断。

保证范围：报告数字/引用可检查，普通 Agent 自由答复主要靠指令要求原样引用；没有完整逐句语义审查器，合法引用不证明每句自然语言都被证据蕴含。

源码：`skills/monthly_spending_report.py`、`skill_runtime/executor.py`、`financial/report_formatter.py`、`application/report_service.py`。

## 4. 安全转账：状态机、幂等、并发资金

**输入：**自然语言意图与用户 Action。**输出：**Provider确认的 Operation 结果。

LLM 只提取recipient query、金额字符串、币种、source hint，不输出ID或风险。收款人精确规范化匹配，两个张三必须用户选择；付款账户只接受 ACTIVE DEBIT/SAVINGS，金额正数且最多两位小数、币种一致、余额足够。

canonical payload含source_account_id/payee_id/标准两位金额/uppercase currency，排序key、紧凑JSON计算SHA-256。Approval绑定hash，字段修改使旧授权失效。默认Approval TTL600秒；强验证TTL300秒、最多3次尝试，绑定具体Approval/Workflow/user。Action expected_version冲突为409。

```text
取得 Security Guard 用户事务锁
  → 有该 Workflow 的原 Operation 时返回原记录
  → 新操作检查写锁
  → 取得 Transfer Risk 用户锁，重读风险
  → 重验 payload / Approval / RED强验证 / Policy / 业务数据
  → 同事务：Operation CREATED + Approval CONSUMED
             + Workflow COMMITTING + Event/Outbox
提交应用事务
  → 写Tool只接受 operation_id
  → handler重载不可变payload与固定idempotency key
  → Provider提交与终态查询
```

SUCCEEDED才成功；FAILED是明确失败；UNKNOWN是结果不明，不换key重提。恢复CREATED可用原key提交，SUBMITTED/UNKNOWN只查询。Operation建立后不重查授权TTL。

幂等与资金竞争分别处理：

```text
相同key：Provider唯一约束 → 原fact/reference → 一次副作用
不同key、同账户：PostgreSQL账户事务锁
  → 重查key
  → balance = fixture_balance − Σ该用户该账户成功转出
  → balance >= 本笔？
  → 原子写成功debit或INSUFFICIENT_FUNDS失败fact
```

余额10000、两笔独立8000并发，最多一笔成功，余额2000。Workflow早期校验只给反馈，Provider锁内判断是最终资金边界。当前只减转出账户余额，没有完整复式账务或收款入账。

源码：`workflows/transfer/`、`application/operation_service.py`、`transfers/mock_provider.py`。

## 5. 动态风险分级

**输入：**用户、币种、业务日、本笔、持久化成功与执行中事实。**输出：**RiskDecision及控制要求。

```text
S = 当日成功Provider转账
F = 当日CREATED/SUBMITTED/UNKNOWN未收敛exposure
P = S + F + 本笔
P <= 1000.00 CNY → YELLOW → Approval
P >  1000.00 CNY → RED → Approval + Reauthentication
```

查询GREEN；转账最低YELLOW；取消订阅固定YELLOW。静态Tool R1/R4与业务风险是两套维度。

累计按Principal.user_id跨账户计算，业务日Asia/Shanghai，保存risk_business_date避免跨日完成漂移。Provider已记终态的同key不重复计执行中；失败不计成功。

提交时用户risk lock保护重读→重评估→控制→Operation入库。并发两笔600，第一笔入库后第二笔累计1200需RED。YELLOW升级时保留payload未变的Approval，进入REAUTH_REQUIRED，不建Operation。payload不变时不自动降级。

源码：`workflows/transfer/risk.py`、`application/transfer_risk_facts.py`、`application/operation_service.py`。

## 6. 订阅识别与成本

**输入：**用户交易、合同fixture、成功取消ledger。**输出：**bounded SubscriptionAnalysisSnapshot。

1. 筛选POSTED DEBIT、非TRANSFER，且SUBSCRIPTION分类或显式审核merchant alias。
2. 有限商户规范化，按normalized merchant + currency分组排序，至少两笔。
3. 所有相邻整数日间隔在25–35天则MONTHLY，在350–380天则ANNUAL，否则不识别周期序列。
4. 当前金额取最新扣费；price_change=最新−上期，比例=差值/上期×100，不要求金额每期相同。
5. 唯一匹配用户合同为MANAGED，无唯一合同为DETECTED_ONLY。取消fact覆盖有效状态，保留历史交易。

```text
月度：monthly_cost=latest，annual_projected=latest×12
年度：monthly_cost=latest/12，annual_projected=latest
```

成本仅ACTIVE，包含仅检测项，按币种分组无FX。MANAGED用合同续费日期；DETECTED_ONLY估计最新日期+30/+365天，不滚动到现实当前月份。默认未来7天续费窗口，工具可指定有限窗口。重复候选只是同merchant多个ACTIVE合同，不推断用户使用情况。

初始28+15+18+88+109=258 CNY/月。晨光健身99→109涨幅约10.101…%，属于一般涨价，未达到30%异常规则。取消仅允许MANAGED+ACTIVE+cancellable，经原Approval/Operation/Provider。

源码：`subscriptions/detector.py`、`subscriptions/service.py`、`workflows/subscription_cancel/`、`subscriptions/provider.py`。

## 7. 四种异常规则

**输入：**用户POSTED DEBIT与分析窗口。**输出：**最多50条、多标签、最高severity、reason/evidence。

默认最近30天，工具支持1–90天。基线为候选交易之前90天、同用户币种、非转账消费；两条金额基线规则至少8样本、中位数m>0。

| 规则 | 条件 | MEDIUM / HIGH |
|---|---|---|
| AMOUNT_SPIKE | amount/m >=4 | [4,8) / >=8 |
| NEW_MERCHANT_HIGH_AMOUNT | 90天基线无该merchant且amount/m >=3 | [3,6) / >=6 |
| RAPID_DUPLICATE | 同merchant/currency/exact amount，10分钟至少两笔 | 2笔 / >=3笔 |
| SUBSCRIPTION_PRICE_SPIKE | 已检测序列最新比上期涨>=30% | [30%,50%) / >=50% |

重复实现分组排序后，用滑动窗口寻找相邻近时段的最大10分钟聚集，以最后一笔为anomaly并关联ID。多规则命中合并标签，严重度取最高，按时间倒序，related IDs最多10。

基线不足只跳过对应金额规则，重复仍运行。源码的insufficient_baseline表示整次没有候选取得足够基线，不能解读为每笔都基线充足。异常不确认欺诈、不自动写锁。

当前对候选逐笔扫描/排序历史，最坏约O(c×n log n)，适用小规模fixture，没有流式风控。源码：`financial/anomaly_detector.py`。

## 8. 安全写熔断

**输入：**强验证失败或绕过安全状态的真实执行信号。**输出：**NORMAL/WRITE_LOCKED。

10分钟计数窗口连续3次验证失败，或5分钟计数窗口5次控制绕过，锁15分钟。窗口从首次信号计时，超时重开，不是逐条事件的滑动队列。未锁定时验证成功清零；已锁时start/verify拒绝。

余额不足、普通校验错误、模型/Provider超时、UNKNOWN和消费异常不计安全信号。信号更新与新Operation创建共用用户事务锁，避免检查/创建竞态。拒绝新写时不消费Approval、不建Operation、不调用Provider；GREEN和原Operation恢复继续，到期下次读状态/写gate懒清理，无unlock worker。

源码：`security/guard.py`、`application/operation_service.py`。

## 9. Plan DAG与条件原文校验

**输入：**多能力/条件原始Message。**输出：**固定Plan与持久步骤事实。

Planner只选ACCOUNT_QUERY、FINANCIAL_ANALYSIS、SUBSCRIPTION_ANALYSIS、TRANSFER_WORKFLOW、SUBSCRIPTION_CANCEL_WORKFLOW，最多8步、2个CONDITION、1个写Workflow。不接受底层Tool、内部ID、写payload、权限、风险。

Validator检查严格schema、唯一key、依赖存在/不重复/不自依赖、DFS无环、写数量；source能力匹配且是依赖，guard指向依赖中的CONDITION，无条件祖先嵌套。图校验O(V+E)，V<=8。

### 阈值grounding

有限解析只读原文“对应指标 + 不少于/至少/达到/>=/大于等于 + 明确金额”，支持3000、3,000、3000.00、¥3000、三千、一百等。规范化Decimal，对照提案值/币种与source span，不能信任Planner自报来源。

“如果余额不少于3000元，给张三转500元”阈值只能3000；业务500不是条件依据。“够”“太多”返回PLAN_CONDITION_THRESHOLD_REQUIRED；错数字、无依据币种拒绝。Planner与Plan持久化前都检查，不能丢条件变成无条件写。

### 决策与执行

仅三个AT_LEAST predicate：账户余额、月度支出、月度订阅成本。读同Plan已完成source的typed bounded output：唯一BalanceResult、对应月份summary或对应currency成本。

```text
TRUE ⇔ Decimal(actual) >= Decimal(threshold)
Decision = 实际值/阈值/币种/source step/时间/canonical source JSON SHA-256
```

省略币种仅允许源唯一币种；缺值/歧义/币种不匹配为FAILED，不能伪装FALSE。hash是来源/完整性引用，不是签名。

source_task_id唯一保存固定DAG，重试不重规划；按ordinal顺序执行ready steps，沿用Task lease/attempt fence，输出<=64KiB。FALSE条件COMPLETED，同事务guarded step SKIPPED/CONDITION_NOT_MET，无预建Workflow；其余完成则Plan/Task COMPLETED。TRUE只进入原Workflow，不代替Approval或风险控制。

等待用户为WAITING_USER，Operation未收敛为WAITING_EXTERNAL；Workflow事件同事务幂等唤醒原Task。写步骤须Workflow/Operation同为SUCCEEDED；最终答复从持久事实确定性整合。

接管撤销当前lease并暂停；resume复用Decision与业务状态。回退遍历目标和后继，整段只读且无linked Workflow才清结果重算；含写Capability即使FALSE跳过也拒绝。TRUE不预留余额，不保证稍后提交资金仍够。

源码：`planning/`、`application/plan_execution_service.py`、`plan_service.py`、`plan_wake_service.py`。

## 10. 持久执行与事件发布

三个专用loop共有形状：

```text
短事务：SELECT due FOR UPDATE SKIP LOCKED → 保存lease/attempt → commit
事务外：LLM / Provider / EventBus工作
短事务：核对owner、lease有效、attempt或version → 结果/调度/终态 + Event/Outbox
```

Task有heartbeat和递增attempt fencing，旧worker不能覆盖新结果；Operation以原key和owner/expiry/version恢复；Outbox失败保留待发布状态。

退避：delay=min(initial×multiplier^(attempt−1), maximum)。Task仅明确可重试系统/运行时错误调度，确定性业务/权限/非法结构错误终止。

业务+Event+Outbox原子提交；发布后确认published_at前崩溃可重发同event_id，所以是**至少一次尝试/发布 + fenced权威完成**。金融副作用另靠Operation/Provider幂等，不能称全系统exactly-once。

published_at表示交给本进程EventBus，不等于浏览器收到。SSE仅提示刷新，Resource API恢复事实。源码：`runtime/task_execution_worker.py`、`operation_recovery_worker.py`、`outbox_publisher.py`、`persistence/repositories/`。
