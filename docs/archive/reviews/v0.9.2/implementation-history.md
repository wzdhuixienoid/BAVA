# 历史档案：每一步实现了什么、如何实现

> 历史材料，保留原记录日期、版本和结论。旧风险规则、待办事项、测试数量与本地部署状态不代表 v0.10.3；当前说明见 [文档导航](../../../README.md)。

基准：v0.9.2。下表按功能演进排序；版本号是历史交付阶段，不代表当前运行多个版本。历史 docs 的“未实现”应结合后续版本判断。

## 1. 一张表读完开发路线

| 步骤 | 功能成果 | 实现方法 | 最值得阅读的源码/文档 |
|---|---|---|---|
| v0.1 骨架 | 对话、消息、异步Task、进度、刷新恢复 | FastAPI+Next.js+PostgreSQL；Conversation/Message/Task/Event持久化；确定性BootstrapRuntime、SSE；空Registry默认拒绝 | `docs/archive/versions/codex-bootstrap-v0.1.md`、`application/conversation_service.py` |
| v0.2 最小Agent | 自然语言查账户/余额 | provider-neutral LLM接口、Fake Provider、手写LLM→Tool→LLM循环；Registry→Policy→Executor；step/tool预算；合成账户/交易/收款人/订阅 | `llm/`、`runtime/manual_agent_runtime.py`、`tools/executor.py` |
| v0.2.2 Runtime | LangGraph和checkpoint恢复 | 两节点StateGraph；统一AgentRuntime协议；PostgreSQL checkpointer；fatal/recoverable错误分类；Manual保留参考。早期stale Task只标INTERRUPTED，后被v0.5.4调度替代 | `runtime/langgraph/`、`docs/archive/versions/runtime-comparison-v0.2.2.md` |
| v0.3.1 金融计算 | 支出、分类、环比、Top N | Decimal、POSTED、自然月、非TRANSFER消费定义、单币种；四个typed只读工具；Golden精确验证 | `financial/analytics_service.py`、`tests/test_financial_golden.py` |
| v0.3.2 金融Agent | 自动路由和消费分析 | Router严格JSON分类，AgentRegistry选择专用只读Agent；成功工具结果构成Snapshot；修正收入排除内部转账 | `routing/request_router.py`、`agents/financial_analysis_agent.py` |
| v0.3.3 月报Skill | 专业结构化报告生成 | Python生成numeric core和display；LLM仅写无数字标题/洞察；schema、evidence_refs、数字/分类/账户校验；Skill无Tool权限 | `skills/monthly_spending_report.py`、`skill_runtime/executor.py` |
| v0.3.4 报告产品 | 对话生成、历史查询、报告页 | immutable Artifact、source Task幂等键、owner-scoped GET；ReportCard、结构化报表与刷新恢复 | `application/report_service.py`、`apps/web/features/reports/` |
| v0.4.1 转账草稿 | 收款人消歧、账户、金额、余额校验 | LLM只提语义字段；确定性Resolver、Decimal校验；持久Workflow及expected_version；终点仅READY_FOR_REVIEW，尚无扣款 | `workflows/transfer/engine.py` |
| v0.4.2 授权 | 确认与强验证 | Approval绑定canonical payload SHA-256；Mock challenge绑定Approval；TTL、尝试上限、草稿修改失效；当时还不能提交 | `workflows/transfer/authorization.py`、`application/workflow_service.py` |
| v0.4.3 提交 | 首次持久Mock资金移动 | 同事务Operation+Approval消费+Workflow；R4写Tool仅Workflow；固定idempotency key、Provider ledger、UNKNOWN/reconcile | `application/operation_service.py`、`transfers/mock_provider.py` |
| v0.5.1 Operation恢复 | 崩溃/未知结果自动收敛 | PostgreSQL due scan、SKIP LOCKED、有期lease、短事务、指数退避；CREATED原key提交，UNKNOWN只查询原操作 | `runtime/operation_recovery_worker.py` |
| v0.5.2 资金并发 | 不同操作不会共同透支 | Provider账户级advisory transaction lock，锁内重查key、有效余额和原子ledger；替代进程内asyncio.Lock的资金边界 | `transfers/mock_provider.py`、`tests/test_provider_concurrency.py` |
| v0.5.3 可靠事件 | 修复业务提交后通知丢失窗口 | business+Event+Outbox同事务；独立leased publisher；至少一次发布，重复通知不重复副作用 | `runtime/event_publisher.py`、`runtime/outbox_publisher.py` |
| v0.5.4 Task持久执行 | HTTP与执行生命周期分离 | PostgreSQL claim/lease/heartbeat、attempt fencing、并发dispatch、重试；HTTP只存Message/Task，Worker执行原Runner | `runtime/task_execution_worker.py`、`persistence/repositories/tasks.py` |
| v0.6.1 身份 | OIDC-ready和多用户隔离 | JWT/JWKS校验、(issuer,subject)→内部user_id；API、Tool和Worker传服务器Principal；owner过滤/404；PKCE与header SSE | `security/authentication/`、`apps/web/lib/auth/` |
| v0.7.1 动态风险 | GREEN/YELLOW/RED | 日成功+执行中+本笔的Decimal exposure；commit前重新评估；用户risk lock保护并发门槛；YELLOW升级RED不先建Operation | `workflows/transfer/risk.py`、`application/transfer_risk_facts.py` |
| v0.7.2 订阅 | 检测、成本、涨价、续费列表、安全取消 | 商户alias+周期窗口；MANAGED/DETECTED_ONLY；Subscription只读Agent；YELLOW取消Workflow、持久Mock取消ledger及恢复 | `subscriptions/`、`workflows/subscription_cancel/` |
| v0.7.3 异常与熔断 | 可解释异常卡、安全写锁 | 历史中位数/重复窗口/新商户/订阅涨价四规则；安全信号计数，写锁15分钟；随后统一Guard用户锁修复TOCTOU | `financial/anomaly_detector.py`、`security/guard.py` |
| v0.8.1 DAG | 多能力串联、接管、只读回退 | 高层Capability Planner+严格Validator；Plan/Step/Dependency表；复用Task Worker和原Workflow；source Task幂等、lease fence、等待/唤醒 | `planning/`、`application/plan_execution_service.py` |
| v0.8.2 条件 | 金额条件TRUE/FALSE与跨场景 | 三个AT_LEAST predicate；typed source+Decimal；Decision/hash持久化；FALSE同事务SKIPPED且零写资源；原文阈值grounding后续收口 | `planning/condition_evaluator.py`、`planning/threshold_grounding.py` |
| v0.8.3 对话体验 | 一请求一回复、Markdown、完成索引 | source IDs关联消息/任务/结果；正文展示工作流，实时过程可折叠；三栏独立滚动，右侧仅索引已完成事实 | `apps/web/features/conversation/`、Codex对话“v0.8.3-agent教程与页面优化” |
| v0.9.1 事实可视化 | Dashboard、余额/风险/DAG/条件卡 | 后端typed projection与display；前端不重算金融事实；双SUCCEEDED生成成功回执；中文状态系统、owner-scoped Demo reset、CNY-only policy | `api/routes/dashboard.py`、`application/workflow_projection.py` |
| v0.9.2 审计与演示收口 | Audit Evidence Chain、preflight、稳定性 | 复用Event+Outbox与当前资源，历史和快照分开；严格货币原文规范化；dev/test只读reference clock；真实smoke/10次报告验证脚本 | `audit/`、`scripts/demo_preflight.py`、`docs/archive/versions/implementation-report-v0.9.2.md` |

源码短路径默认相对 `apps/api/src/banking_api/`；`apps/web`、`docs`、`tests`、`scripts`按仓库根或明确模块解释。更详细版本证据在 `docs/implementation-report-v*.md` 与 `docs/test-results-v*.md`。

## 2. 六种概念如何配合

| 概念 | 项目中的作用 | 当前实例 |
|---|---|---|
| Router | 给当前请求选择路径，不授权 | MINIMAL_BANKING / FINANCIAL_ANALYSIS / TRANSFER / SUBSCRIPTION / COMPLEX_PLAN |
| Agent | 在小范围工具中决定下一步查询 | MinimalBanking、FinancialAnalysis、SubscriptionAnalysis三个定义，共用LangGraph Runtime |
| Skill | 稳定地把可信输入做成专业产物 | MonthlySpendingReport：Snapshot→报告 |
| Workflow | 按固定规则完成需要授权的业务 | Transfer、SubscriptionCancel |
| Tool | 可执行的具体能力，带输入/输出类型和权限 | account.get_balance、transaction.spending_summary、transfer.commit等 |
| Plan | 协调已有高层能力与确定性条件 | 固定DAG；不是自由调用底层Tool的超级Agent |

三个Agent是专门的配置/职责划分，没有运行自由协商的Multi-Agent系统。LangGraph负责查询循环和checkpoint；银行业务状态由Application/PostgreSQL管理。

## 3. 建议代码阅读顺序

1. `main.py`：了解Registry、三个Agent、两个Workflow和三个worker如何组装。
2. `application/conversation_service.py` → `runtime/task_execution_worker.py` → `runtime/task_runner.py`：看一条消息如何执行。
3. `routing/request_router.py` → `runtime/langgraph/graph.py` → `tools/executor.py` → `policy/service.py`：看模型如何被约束。
4. `financial/analytics_service.py` → `skills/monthly_spending_report.py` → `skill_runtime/executor.py`：看金融数字与解释的分工。
5. `workflows/transfer/` → `application/workflow_service.py` → `application/operation_service.py` → `transfers/mock_provider.py`：看真正写入的安全边界。
6. `planning/` → `application/plan_execution_service.py` → `audit/projection.py` → 前端卡片：看复杂任务与可核验证据。

当前fixture有4账户、140交易、6收款人、5订阅合同。早期v0.2文档的138笔交易是历史数目，不能作为当前数据清单。有效余额使用fixture减成功Mock ledger转出；没有完整复式账务/收款入账。
