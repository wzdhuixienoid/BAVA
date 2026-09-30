# v0.8.1 受约束任务规划与持久化 DAG

1. **路由门槛。** RequestRouter 保留单能力 Agent / Workflow 路由；只有多个已有能力协作才进入 COMPLEX_PLAN。分析并生成报告仍是单个 Financial vertical slice。条件自动执行 fail closed。
2. **Capability。** 静态 registry 注册 ACCOUNT_QUERY、FINANCIAL_ANALYSIS、SUBSCRIPTION_ANALYSIS、TRANSFER_WORKFLOW、SUBSCRIPTION_CANCEL_WORKFLOW，映射三个现有 Agent 和两个现有 Workflow。
3. **不能选择 Tool。** Registry 不 resolve Tool；transfer.commit、Operation、SQL 等既不属于 enum，也不能通过 extra 字段进入 proposal。Planner 无执行或授权入口。
4. **Schema。** PlanProposal 只有 goal_summary、steps；step 只有 step_key、display_title、capability、depends_on、可空 subtask_query。strict + extra=forbid；目标/标题/query 有长度上限，无 hidden reasoning。
5. **Validator。** schema → capability → 唯一 key / 存在的依赖 / 禁止重复依赖与自依赖 → DFS cycle check → ValidatedPlan。非法 proposal 仅在内存，Task 留明确错误，不保存非法 DAG。
6. **最多一个写 Workflow。** 统计 write Capability，两个转账或转账+订阅取消拒绝 PLAN_MULTIPLE_WRITE_STEPS_UNSUPPORTED。本版不实现多笔金融 transaction plan。
7. **持久化。** 0016 仅新增 plans、plan_steps、plan_step_dependencies 和必要索引/约束；source_task_id UNIQUE；ordinal 稳定；dependency composite PK 防重复并覆盖 step_id 查询索引。历史 schema 不改。
8. **没有 Plan worker。** PlanExecutionService 是现有 Task runner 调用的小型顺序执行服务。沿用 TaskExecutionWorker 的 claim、lease、heartbeat、attempt，无第二套 durable authority。
9. **Fencing。** 每次 Plan 创建、Step 状态/输出、Plan terminal、最终 Message 持久化，先按 Task ID + owner + attempt + 未过期 lease 获取 Task 行锁。控制动作锁 Task 再锁 Plan，并清除旧 lease。旧调用结束后无法写回；Workflow 创建在提交前再次 execution_check。
10. **Task retry。** 持久路由使用 planner:constrained executor identity，重试直接 reload source_task_id 对应 Plan，不再调用 Router/Planner、不修改图。保留历史 executor_type enum，不增加 Task migration。
11. **只读 Step。** 调用现有 AgentRegistry 和 runtime，Principal 由服务器从 Task ownership 构造。各 step/attempt 使用独立 checkpoint thread identity，但没有新 Task。成功工具结果组成 Financial/Subscription typed snapshot 或账户工具结果；总序列化大小上限 64 KiB。
12. **Workflow Step。** 原始 Message 交现有 IntentExtractor；source_task_id UNIQUE 用于复用，链接写回 crash window 也能找回。Planner 无金额、账户、收款人、订阅内部 ID 或业务风险 authority。
13. **WAITING_USER。** 草稿缺输入、READY_FOR_REVIEW、REAUTH_REQUIRED、READY_FOR_COMMIT 均暂停编排，Step/Plan/Task WAITING_USER。无需 automatic retry，不自动 Approval、强验证或 commit。
14. **WAITING_EXTERNAL。** COMMITTING 或已有非 terminal Operation 时三层 WAITING_EXTERNAL。UNKNOWN 不生成新 intent/key，仍由原 OperationRecoveryWorker 查询原事实。
15. **唤醒。** EventPublisher 在明确 Workflow 状态事件 transaction 内调用 PlanWakeService，锁 Task→Plan，等待中的 source Task 幂等改为 PENDING。覆盖用户 action、foreground Operation 和 Recovery terminal；无新增 polling loop。
16. **人工接管。** take-over 将 Plan PAUSED、manual_takeover=true，Task WAITING_USER，并清除当前 lease。后台旧读取无法完成。关联 Workflow 可以继续手工操作，wake helper 在 manual_takeover 期间不 reschedule。
17. **Resume。** 必须 PAUSED，清除 manual flag，重新调度同一个 source Task；新 attempt reload authoritative Workflow 再推进。
18. **安全回退。** 遍历目标及所有 descendants。整个范围只读且无 linked Workflow 才重置 PENDING，清空 output/error/timestamps，上游保持；恢复同一个 Task、Plan、固定图。
19. **不支持金融回退。** 任何写 Capability 或 linked Workflow 使范围不安全。Plan rollback 不调用 Operation/Provider，不删除 ledger、不撤销成功转账、不恢复订阅。
20. **Prompt Injection。** enum 和 extra=forbid 拒绝低层能力及风险/权限字段；Planner 无底层工具清单。最终回答不使用 Planner 标题或 Agent 自由文本来宣称成功，只渲染 bounded authoritative facts；用户传入的标题不能伪造转账成功。
21. **Principal。** Plan GET/list/actions 全部 user_id scoped，跨用户 ID 为 404。Query 只是任务文字，不提供 Principal；实际工具 authority 不变。HTTP credentials 不进入 Plan、event 或 checkpoint。
22. **Existing Operation + WRITE_LOCKED。** Commit/prepare 在取得现有 Security Guard user advisory lock 后先查原 Operation，原记录先于 write gate、版本校验和 Approval consumption 返回。没有新 key/Approval/Provider intent；新 Operation 仍检查原安全边界。
23. **Recovery。** 原 OperationRecoveryWorker 主算法没有改动，也不新增当前 Security Guard 校验。已持久化 CREATED/SUBMITTED/UNKNOWN 是已经授权的 intent，后续写锁不取消它。
24. **实际验证。** 新增 Plan 定向测试；真实 PostgreSQL 定向验证 migration 0015→0016、DAG 唯一性、stale worker fence、UNKNOWN + WRITE_LOCKED Recovery/wake。真实 HTTP + 当前 LLM 的 A/B 产品 smoke 均通过。完整检查结果见 test-results-v0.8.1.md。
25. **限制。** MAX_PLAN_STEPS=8；顺序执行；一个写 Workflow；静态 registry；复杂月度 Report Artifact 暂未注册，会拒绝，独立 Report 路径仍可用；无 Plan cancel API；不增加跨进程 SSE broker。结构化最终回答使用确定性 renderer，并非新的 LLM synthesis。
26. **范围。** 本版交付止于上述能力；条件 DAG、多个 side effect、动态重规划、冲正、自由 Agent 协商、RAG/MCP/Memory、插件平台均未实现。
