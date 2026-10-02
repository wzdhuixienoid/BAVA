# v0.8.2 Implementation Report

当前版本：v0.8.2。受约束条件节点和跨场景联动 COMPLETE。本版仅扩展固定 Plan DAG，没有规则引擎、额外 Worker 或 v0.9 功能。

1. **增加 Condition Step 的原因**：让已有只读结果控制后续步骤是否进入业务流程，同时让 Planner 无法判断真实金额或授予写入权限。
2. **Condition 不是 Capability**：`CAPABILITY / CONDITION` 为两个 Step kind。Condition 没有 Agent、Tool 或 Provider 注册项，`capability` 为 null，executor_kind 为 CONDITION。
3. **三个 Predicate**：`ACCOUNT_BALANCE_AT_LEAST` → ACCOUNT_QUERY；`MONTHLY_SPENDING_AT_LEAST` → FINANCIAL_ANALYSIS；`SUBSCRIPTION_MONTHLY_COST_AT_LEAST` → SUBSCRIPTION_ANALYSIS。均使用 >=，没有其他比较或 FX。
4. **Planner schema**：按 kind 判别的 CapabilityStepProposal / ConditionStepProposal union，均 extra=forbid。ConditionSpec 只接受 predicate、source_step_key、有限非负 Decimal 字符串 threshold 和可省略 currency。能力步骤最多一个 guard_condition_step_key；写步骤不接受 subtask_query。
5. **Validator**：复用唯一 key、依赖存在、无环和最多一个写 Workflow 规则；增加 source 存在、predicate/source 匹配、source 属于依赖、guard 指向 CONDITION 且属于依赖、最多两个条件。包括间接祖先在内的条件嵌套会拒绝。无写的查询加条件 Plan 合法。
6. **不使用表达式引擎**：没有 JSON path、字段映射、任意表达式、AND/OR 或数据运算，缩小语义与权限边界。ELSE 和明确不支持的条件在规划前拒绝；条件请求不能被 Planner 省略成无条件写入。
7. **Evaluator 的输入**：只读取同一 Plan 中已完成 source 的 bounded output_json。账户适配器要求一个明确选中账户的 BalanceResult；账户列表本身不构成余额。金融适配器使用 FinancialAnalysisSnapshot.spending_summary 的对应月份总支出；订阅适配器使用现有 monthly_cost_by_currency。没有再次调用 LLM、Tool、Workflow 或 Provider。
8. **金额和币种**：比较全部使用 Decimal。指定币种没有对应源值时 CONDITION_CURRENCY_MISMATCH；省略币种而有多个币种时 CONDITION_CURRENCY_REQUIRED；空值、多个账户余额、无对应月份总支出、非有限金额或非法结构为 CONDITION_INPUT_UNAVAILABLE。不能相加或换汇。
9. **source_output_hash**：整个 bounded source output 以排序 key、紧凑分隔符、UTF-8 canonical JSON 序列化后计算 SHA-256。Decision 保存 predicate、source UUID、hash、Decimal 实际值/阈值字符串、实际币种、outcome 和 evaluated_at；不保存 hidden reasoning。
10. **FALSE 分支**：Condition Step 本身 COMPLETED；直接 guarded Step 同事务 SKIPPED / CONDITION_NOT_MET。下游继续传播正常条件跳过；即使另一独立依赖尚在等待，也不会误记为失败跳过。
11. **FALSE 不是 failure**：其余步骤均完成或正常条件跳过时，Plan / Task COMPLETED。最终回答明确条件未满足、没有启动后续业务。
12. **无法判断不是 FALSE**：缺少合法 source 或币种不匹配时 Condition FAILED，后续 SKIPPED / UPSTREAM_NOT_COMPLETED，Plan / Task FAILED。
13. **TRUE 不是授权**：只允许进入已有业务流程。Approval、RED Reauthentication、Security Guard、commit 时 Risk 和 Provider authoritative balance 都保留；快照没有资金预留，也不保证稍后余额仍足够。
14. **FALSE 不预建 Workflow**：创建/复用 Workflow 位于 guarded Capability 真正就绪之后；FALSE 路径无 Workflow、Approval、Reauthentication、Operation 和 Provider 写入。
15. **Task fencing**：Decision 写回前重新验证原 Task lease_owner、attempt、未过期 lease 和 RUNNING 状态，锁 Task 后锁 Plan。Decision、Condition COMPLETED、直接 guarded skip、Event 和 Outbox 同事务提交；旧 Worker 不得写回或启动 Workflow。
16. **retry / rollback**：PENDING / RUNNING 未持久 Decision 的条件可纯计算重试；COMPLETED 条件复用 Decision，不重新 Planner。只读回退清除输出、Decision、错误和时间戳；重新读取产生新 hash。范围含写 Capability 即使 FALSE 从未创建 Workflow，仍 PLAN_ROLLBACK_NOT_SAFE。
17. **Human-in-the-loop**：TRUE 后只创建/复用已有 Workflow，业务意图仍来自原始 Message。WAITING_USER / WAITING_EXTERNAL、原 Task wake、manual take-over / resume 沿用现有实现；接管期间业务卡可操作，恢复后读取当前状态和既有 Decision。
18. **Prompt Injection**：outcome、condition_result、actual_value、风险/Approval/Operation 权限字段、表达式和多个 guards 均被 schema 拒绝；真实条件结果仅由实际 source 决定。注入要求强制 TRUE 或跳过确认不能影响实际比较或用户确认。
19. **跨用户隔离**：Condition 不接受 user_id、principal_id 或 subject，只能消费已由服务器 ExecutionPrincipal scoped 的 source。Plan 查询和操作继续使用 ownership 校验；用户文字中的 user-B 提示不能改变工具 Principal。
20. **产品 Smoke**：真实 HTTP、当前配置 LLM、独立 banking_condition_smoke_test 数据库。A 的阈值 999999 导致 FALSE，五类写资源/事实均 0，Plan / Task COMPLETED，中文明确未启动转账。B 阈值 3000 导致 TRUE；通过现有 API 明确选择张三候选项后 READY_FOR_REVIEW / YELLOW / WAITING_USER / 0 Operation；明确 approve 和 commit 后一个 Workflow、Approval、Operation、Provider 转账记录，最终全链路成功。没有绕过 Risk 或用户确认。可选 C 未运行，订阅条件跨场景由 PostgreSQL UNKNOWN 测试覆盖。
21. **完整最终 regression 收尾**：最终完整后端及 PostgreSQL suite 的连续运行结果见本版 Test Results，采用最后成功的整次运行，不拼接定向结果。包括源 Task 唯一性、0016→0017、条件 fencing/接管、既有 Operation + WRITE_LOCKED、UNKNOWN Recovery 和历史 Provider 并发回归。基线中缺失但已被 router 引用的 plans.py 已补回，保留原 Plan API 范围。
22. **限制**：最多 8 Steps、2 Conditions、一个写 Workflow；每个 Capability 最多一个 guard；仅三种金额 >= predicate。没有 ELSE、nested conditions、任意表达式、AND/OR、loops、多副作用、动态 replan、Condition API 或新增 Worker。只读快照可能过期，最终写入仍以原业务 commit 验证及 Provider 事实为准。


## v0.8.2 correctness 收尾（2026-10-02）

新增 ConditionThresholdGroundingValidator，仅使用源用户 Message 匹配三个 predicate 的“指标 + 不少于/至少/达到/>=/大于等于 + 明确金额”有限语法。支持 Decimal 字符串、逗号分组、¥/￥、元/块和普通中文整数（如三千、一百）。GroundedConditionThreshold 保留 predicate、Decimal amount、原文币种和 source span；不接受 Planner 自报 threshold_source。

模糊条件在调用 LLM 前以 PLAN_CONDITION_THRESHOLD_REQUIRED 拒绝；已提出但没有原文依据或选错数字的 proposal 以 PLAN_CONDITION_THRESHOLD_NOT_GROUNDED 拒绝。Planner 和 Plan persistence 前都执行 grounding；条件不得被省略成普通写入。Task 错误提示用户提供明确金额，没有增加 clarification 状态。匹配限定条件从句，不能从业务金额、goal_summary、display_title 或 subtask_query 取得依据；相同 predicate 的冲突阈值及未支持写法保守拒绝。

明确币种与 proposal 冲突、或 proposal 在原文无币种时自行指定币种，均 PLAN_CONDITION_CURRENCY_NOT_GROUNDED。proposal 省略币种而用户明确币种时，后端将原文币种绑定到既有 ConditionSpec；双方都未说明币种时沿用 source 唯一币种规则。未改 ConditionEvaluator、写业务 payload 提取、持久化 schema、前端、版本号或 migration。

Alembic 仅增加 path_separator=os，保留 env.py、迁移行为和 version locations。定向升降级测试无 path_separator warning；最终整套结果见 Test Results。原始 Message 模糊条件的集成测试验证 0 Plan / Workflow / Operation，采用该证明，不重跑历史产品 smoke。
