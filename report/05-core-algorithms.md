# 当前 Agent 的核心算法说明

v0.9.2。核心是**受约束模型选择 + 确定性金融计算 + 状态机 + 幂等/并发/恢复协议**。没有训练自有模型、强化学习银行策略、Fraud ML或向量检索。以下源码短路径相对 `apps/api/src/banking_api/`。

## 1. 路由和 Agent Loop

**输入：**当前原始用户消息、服务器Principal、有限上下文。**输出：**执行者、成功工具事实、自然语言解释。

Router让LLM输出严格JSON route/requested_output/confidence，Pydantic拒绝非法/额外字段，最多一次格式重试；确定性条件/多能力规则再调整路由。分类不授予权限。简单请求选择原Agent/Workflow，复合请求选择受约束Plan。

```text
START → llm
          ├─ final / fatal error → END
          └─ tool calls → tool
                           ├─ fatal error → END
                           └─ success / recoverable error → llm
```

ContextBuilder提供Agent指令、最近10条USER/ASSISTANT、当前任务、允许工具schema和本次Runtime结果；默认最多6次Agent LLM step、4次Tool call。Router/Planner/提取器/报告Skill调用在各自边界计数，不是整个请求总共只调用6次模型。

每次Tool：注册查找→caller/Principal/allowlist/风险与副作用Policy→输入schema→handler→输出schema。参数错误可在预算内让模型修正；未知、越权、执行或输出错误直接终止。Agent只读，写Tool在确定性Workflow边界。

**限制：**Router/Planner/写意图提取主要看当前消息，不拥有统一对话消歧；条件同义句遗漏见R02。LangGraph checkpoint不替代Domain业务事实。源码：`routing/`、`runtime/langgraph/graph.py`、`context/builder.py`、`tools/executor.py`、`policy/service.py`。

## 2. Decimal 金融统计

**输入：**Principal范围内合成交易、YYYY-MM、可选账户。筛选UTC自然月左闭右开、POSTED；每笔金额非负，方向区分收支。

```text
Spending = POSTED ∧ DEBIT ∧ category != TRANSFER
Income   = POSTED ∧ CREDIT ∧ category != TRANSFER
total_spending = Σ amount(Spending)
category_share = category_amount / total_spending
absolute_change = current_spending − previous_spending
percentage_change = absolute_change / previous_spending × 100
```

上期为0时环比百分数为null；总支出为0时分类比例为0。同次聚合混币种拒绝，无FX。比例Decimal precision28；分类按金额降序/category升序；Top N按金额降序、时间升序、交易ID升序，最多20。默认工具Top5，不传整月raw流水给模型。

Golden例：`16547.30−9333.20=7214.10`，精确环比`77.29503278618265975228217546%`，展示`+77.3%`。金融月分界UTC与转账日累计Asia/Shanghai是不同口径，当前不是统一业务时区月报。

扫描分组O(n)，排序O(n log n)，当前内存fixture规模140交易。源码：`financial/analytics_service.py`。

## 3. 可信报告生成

1. 从成功Tool结果构造FinancialAnalysisSnapshot，验证period、scope、currency、summary/category一致及tool evidence。
2. Python生成numeric core；ReportFormatter生成两位金额、一位百分比，展示使用ROUND_HALF_UP，原Decimal保留。
3. LLM在tools=[]下仅生成headline与2–5条insight，每条引用已存在evidence_refs；不拥有金融数字计算权。
4. 严格JSON/schema、引用、未知category/account token、阿拉伯/全角/中文数字与部分英文数词校验；最多一次修正，仍非法则失败。
5. 合并immutable报告，保存snapshot hash、Skill/Report版本；`(source_task_id, report_type, report_version)`唯一防同Task重试重复产物；GET不重新生成。

summary/category必需，comparison/Top缺失可PARTIAL。合法引用不证明每一句解释被证据蕴含；没有semantic entailment verifier。本轮没有再次调用真实LLM，历史10次固定报告通过属于有限窗口证据。源码：`skills/monthly_spending_report.py`、`skill_runtime/executor.py`、`application/report_service.py`。

## 4. 转账解析、授权与状态机

LLM只提recipient query、金额字符串、currency、source hint，不输出内部ID、风险或权限。收款人/手机尾号别名用normalize后精确匹配，多名必须用户选；账户限ACTIVE DEBIT/SAVINGS。金额>0且最多2位小数，币种与账户一致，当前风险策略仅CNY，余额必须够。

canonical payload由source_account_id、payee_id、两位标准金额、uppercase currency组成；sort_keys+紧凑JSON→SHA-256。Approval绑定hash、owner、Workflow和TTL（默认600s）；草稿修改使旧授权失效。RED Reauth绑定具体Approval，TTL默认300s，默认最多3次失败。Action用expected_version防旧窗口覆盖。

```text
Draft / WAITING_FOR_INPUT → READY_FOR_REVIEW
  → Approval
    ├─ YELLOW → READY_FOR_COMMIT
    └─ RED → REAUTH_REQUIRED → VERIFIED → READY_FOR_COMMIT
  → commit-time重新校验
  → Operation CREATED + Approval CONSUMED + Workflow COMMITTING
  → Provider → Workflow/Operation SUCCEEDED 或 FAILED
```

UNKNOWN是结果不明，不能伪装成功或换key重提。Reauth非ASCII比较异常见R01；未知币种识别漏项见R03，不能把schema严格等同于原文语义已全部校验。源码：`workflows/transfer/`、`application/workflow_service.py`。

## 5. 动态风险与并发认证门槛

**输入：**user_id、币种、真实业务日、当日成功Provider事实、执行中Operation、本笔金额。

```text
S = 当日成功转账总额
F = 当日CREATED / SUBMITTED / UNKNOWN未收敛暴露
P = S + F + 本笔
P <= 1000.00 CNY → YELLOW → Approval
P >  1000.00 CNY → RED    → Approval + Reauth
```

累计按用户跨账户、Asia/Shanghai自然日；risk_business_date固定到Operation，避免跨日收敛漂移。Provider已有终态的同key不再计执行中，FAILED不计成功。查询GREEN、转账最低YELLOW、取消订阅固定YELLOW；静态Tool R1/R4与业务GREEN/YELLOW/RED是独立维度。

提交前按固定顺序取得Guard用户锁→Risk用户锁，重读exposure→评估→授权检查→创建Operation→事务提交。并发两笔600时，第二笔看见第一笔执行中累计1200，升级RED并在补验证前不创建Operation。payload不变时RED不自动降级。

保存RiskDecision中的本笔、成功、执行中、预计、阈值、日期、时间、reason/control要求，用于UI/Audit。源码：`workflows/transfer/risk.py`、`application/transfer_risk_facts.py`、`application/operation_service.py`。

## 6. 幂等与最终余额控制

```text
应用短事务：授权检查 → Operation+消费Approval+Workflow+Event/Outbox → COMMIT
事务外：写Tool仅收operation_id，重载不可变payload与固定idempotency key
Provider短事务：账户级advisory lock
  → 重查同key事实
  → effective_balance = fixture_balance − Σ成功ledger转出
  → 余额足够？原子记SUCCEEDED / 否则FAILED(INSUFFICIENT_FUNDS)
```

同key由Provider ledger唯一约束/原事实重放保护，一次副作用；不同key同账户由锁内实时余额保护，不能只靠幂等。10000余额、两笔8000并发，最多一笔成功，剩2000；不同账户不全局串行。

Provider锁key用有namespace的SHA-256映射signed bigint，在不同Python进程稳定。Provider I/O不跨应用事务持有长行锁。Mock只实现转出余额和取消事实，无复式账务、收款入账、预留/hold/capture。

源码：`transfers/mock_provider.py`、`application/operation_service.py`。当前PostgreSQL并发/恢复回归已通过。

## 7. 订阅检测与成本

筛POSTED DEBIT非TRANSFER，候选须SUBSCRIPTION分类或显式merchant alias；规范化商户+currency分组，至少2笔。全部相邻整数日间隔25–35为MONTHLY、350–380为ANNUAL，否则不识别，不由模型判断周期。

```text
monthly: monthly_cost=最新扣费；annual_projection=最新扣费×12
annual:  monthly_cost=最新扣费/12；annual_projection=最新扣费
price_change=最新−上一期；percent=price_change/上一期×100
```

唯一匹配用户合同→MANAGED，其他→DETECTED_ONLY；成功取消ledger覆盖ACTIVE为CANCELLED。成本仅ACTIVE、按币种分组，不FX；仅检测项目也纳入成本。Managed用合同日期，detected估计最后日期+30/+365天，不滚动旧fixture到当前月份。

初始月成本28+15+18+88+109=258；取消星幕后230。晨光99→109约10.1%，是涨价但不是>=30%的价格异常。取消必须原YELLOW Workflow+Approval+Operation/Provider，只有MANAGED+ACTIVE+cancellable。

**边界：**不是从任意商户自由识别全部订阅，无使用频率推断、主动提醒或真实取消API。源码：`subscriptions/detector.py`、`subscriptions/service.py`、`workflows/subscription_cancel/`。

## 8. 四种异常检测

默认最近30天（工具范围1–90），历史基线为该候选之前90天、同用户/币种、非转账消费；金额规则至少8样本、中位数m>0。不同于完整反欺诈平台。

| 规则 | 判定 | 严重度 |
|---|---|---|
| AMOUNT_SPIKE | amount/m >=4 | >=8 HIGH，其余MEDIUM |
| NEW_MERCHANT_HIGH_AMOUNT | 基线无该商户且amount/m>=3 | >=6 HIGH，其余MEDIUM |
| RAPID_DUPLICATE | 同商户/币种/精确金额，10分钟内至少2笔 | >=3笔HIGH，2笔MEDIUM |
| SUBSCRIPTION_PRICE_SPIKE | 周期序列最新比上一期涨>=30% | >=50% HIGH，其余MEDIUM |

重复分组排序后划近邻段，再滑动窗口取最大10分钟聚集、最后一笔作提示并关联交易。多规则命中合并labels/evidence，严重度取最高，时间倒序最多50项，关联ID最多10。

基线不足只跳过依赖基线的规则；insufficient_baseline表示整次没有候选取得足够基线，不表示每笔样本充足。逐候选构造/求基线，规模上界约O(c×n log n)，小fixture适用；未实现流式索引。异常不等于欺诈，不自动写锁。源码：`financial/anomaly_detector.py`。

## 9. 安全写熔断

10分钟窗口连续3次强验证失败，或5分钟窗口5次控制绕过→WRITE_LOCKED 900s。窗口从首次信号计时，超时重开，不是事件滑动队列。未锁定时验证成功清失败计数；普通余额/参数/模型/Provider失败、UNKNOWN和交易异常不计安全失败。

状态和计数持久化，信号与新Operation gate共享同用户事务锁，消除检查后创建的TOCTOU。锁定时不消费Approval/不创建新Operation/不调Provider；GREEN和已有Operation恢复继续。到期下一次检查惰性清理，无管理员手动解锁界面。R01非ASCII路径不进入失败计数，需要修复。

源码：`security/guard.py`、`application/operation_service.py`。

## 10. 受约束 DAG、条件与回退

Planner只选择ACCOUNT_QUERY、FINANCIAL_ANALYSIS、SUBSCRIPTION_ANALYSIS、TRANSFER_WORKFLOW、SUBSCRIPTION_CANCEL_WORKFLOW。最多8步骤、2CONDITION、1写Workflow；禁止内部ID、写payload、权限、风险、Tool；写意图从原始Message由原Workflow提取。

Validator用严格判别schema、唯一key、依赖存在/不重复/不自依赖、DFS无环、写数量、条件source能力匹配和依赖关系、guard指向条件，无nested conditions。图校验O(V+E)，V<=8。

原文grounding只认有限“指标+不少于/至少/达到/>=/大于等于+明确金额”；Decimal规范化阿拉伯/分组/部分中文数字与币种，检查source span，不能拿动作金额500充当余额阈值3000。模糊“够/太多”拒绝。**这层对同义句与币种的覆盖不是完整自然语言解析，R02/R03揭示仍有漏项。**

三个predicate为ACCOUNT_BALANCE_AT_LEAST、MONTHLY_SPENDING_AT_LEAST、SUBSCRIPTION_MONTHLY_COST_AT_LEAST。Evaluator只消费已完成source的typed bounded output，省略币种只接受唯一币种，不换汇；缺值/歧义/不匹配→FAILED，不伪装FALSE。

```text
TRUE ⇔ Decimal(actual) >= Decimal(threshold)
Decision = actual / threshold / currency / source step / time / canonical source SHA-256
FALSE → 同事务guarded Step SKIPPED(CONDITION_NOT_MET)，不建业务写资源
TRUE  → 原Workflow，继续Approval/风险/Guard，不预留余额
```

Plan/source_task_id唯一，重试复用同图，按ordinal顺序推进ready steps，并不并行执行DAG节点。WAITING_USER等用户、WAITING_EXTERNAL等Operation；Workflow状态改变同事务幂等唤醒Task。写步骤成功仍需双SUCCEEDED，最终回答确定性整合事实。

接管撤销lease/fence并PAUSED，resume复用Decision/业务状态。Rollback求目标与后继闭包；只有整段只读且无linked Workflow才清输出/Decision重算。含写Capability即使FALSE也拒绝，不能逆转资金副作用。source hash是引用与完整性依据，不是数字签名。

源码：`planning/`、`application/plan_execution_service.py`、`application/plan_service.py`、`application/plan_wake_service.py`。

## 11. Worker恢复、事件与审计

三个专用loop共有协议：

```text
短事务：due + FOR UPDATE SKIP LOCKED → lease/attempt → commit
事务外：LLM / Provider / EventBus执行
短事务：核对owner / lease / attempt或version → 结果或重试 + Event/Outbox
delay = min(initial × multiplier^(attempt−1), maximum)
```

Task有heartbeat与递增attempt fence，旧worker不能完成新结果；临时错误重新调度，确定性输入/权限错误终止。退避延迟上限不等于所有worker都有有限重试次数。Operation用原key恢复；CREATED可原key提交，SUBMITTED/UNKNOWN查状态，不重新消费授权。

business+Event+Outbox原子提交；publisher发布成功后、确认published_at前崩溃会重发同event_id。因此是**至少一次执行尝试/通知 + fenced权威完成**，金融副作用单独依赖Provider幂等，不能称全系统exactly-once。

Audit按持久Event.sequence构成结构化历史，再附当前owner资源快照；保留风险升级/授权失效/UNKNOWN，不从自然语言制造结果。最多1000事件并标截断，不保存凭证/COT，Event应用append-only无数据库签名/WORM。SSE为进程内通知、无replay，刷新资源API恢复；多进程限制见K01。

源码：`runtime/task_execution_worker.py`、`runtime/operation_recovery_worker.py`、`runtime/outbox_publisher.py`、`runtime/event_publisher.py`、`audit/`。
