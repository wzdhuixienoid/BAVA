# AI Banking Agent — Report Artifact + Structured UI v0.3.4

Status: `IMPLEMENTED AND VERIFIED`

实施日期：2026-09-23。本轮完成 Financial Analysis 的第一条完整产品 Vertical Slice：用户请求经过 Router、FinancialAnalysisAgent、MonthlySpendingReportSkill，形成不可变 Report Artifact，并通过 Reports API 和中文 Structured UI 展示。`ManualAgentRuntime` 未修改。

## 1. Report data model

首个正式 Artifact 类型为 `MONTHLY_SPENDING`。Report 持久化字段包括：

```text
report_id / user_id / conversation_id / source_task_id
report_type / report_version
skill_id / skill_version
period
content_json
source_snapshot_hash
created_at
```

`content_json` 保存 Skill 当时产生的完整 `MonthlySpendingReport`，而不是只保存 Snapshot 后在读取时重建。历史 Artifact 因此不会随 Prompt、Formatter、模型或 Skill 的后续变化而改变。

## 2. Persistence、immutability 与 idempotency

Alembic `0005_reports.py` 同时增加 `tasks.requested_output` 和 `reports` 表。Report 使用 `(source_task_id, report_type, report_version)` 唯一约束实现强幂等；重复持久化同一 Task 的同版本报告时返回既有 Artifact。

`ReportRepository` 只实现创建或获取、按当前用户读取、按当前用户分页列举。`ReportService` 负责 typed content、ownership 和 canonical Snapshot SHA-256。详情请求始终同时使用 `report_id + user_id`，不属于当前用户的资源返回 404，不泄漏资源是否存在。

Report API 没有 POST、PUT、PATCH 或 DELETE；当前 Artifact 创建后不可变。

## 3. requested_output routing

`RouteDecision` 扩展为：

```text
route: MINIMAL_BANKING | FINANCIAL_ANALYSIS | UNSUPPORTED
requested_output: ANSWER | MONTHLY_REPORT
confidence
```

账户/余额和普通分析仍使用 `ANSWER`；“生成一份 2026 年 8 月消费报告”等请求选择 `FINANCIAL_ANALYSIS / MONTHLY_REPORT`。`requested_output` 在 Router 成功后写入 Task，是 Backend authoritative state，前端不解析用户文本推断执行模式。

包含报告和转账意图的混合请求仍路由到只读 FinancialAnalysisAgent；Router 不扩大 Agent capability，任何写 Tool 调用都会 fail closed。

## 4. Agent → Skill → Artifact pipeline

```text
RequestRouter(FINANCIAL_ANALYSIS / MONTHLY_REPORT)
    → FinancialAnalysisAgent
    → deterministic Financial Tools
    → FinancialAnalysisSnapshot
    → SkillRegistry
    → SkillExecutor(skill:monthly-spending-report v1, tools=[])
    → MonthlySpendingReport
    → ReportService / ReportRepository
    → immutable Report
```

报告模式下 Agent Context 明确要求 `spending_summary` 和 `category_breakdown`，并优先补充 `compare_periods` 与 bounded `top_transactions(limit=5)`。Agent 中间自然语言答案不会保存为用户可见消息；它只提供 Snapshot。Skill 成功、Artifact 持久化以后，系统才创建一条简短 Assistant confirmation。

Skill 仍不查询银行数据、不拥有 Tool、不计算金融指标。报告 numeric core、排序与 display 字段由 Python 生成；LLM 只负责经过 evidence 与数字泄漏校验的 headline/insights。

## 5. Task lifecycle

同一个 `BANKING_REQUEST` Task 贯穿 Agent、Skill 和持久化，primary executor 仍为：

```text
executor_type = AGENT
executor_id = agent:financial-analysis
```

成功路径的事务顺序是：

```text
Skill completed
    → Persist Report
    → Update Task.output with report reference
    → Persist report.generated
    → Persist one Assistant confirmation
    → Task COMPLETED
    → Commit
    → publish committed events
```

因此 `report.generated` 可见时，GET API 已能读取 Artifact；Artifact 创建前 Task 不会进入 `COMPLETED`。Agent、Skill 或 persistence 任一阶段失败都会令 Task 失败，不保存半成品，不发送成功确认。持久化异常使用 `REPORT_PERSISTENCE_FAILED`。

Task output 在报告模式下包含 `requested_output`、`agent_id`、`analysis_snapshot`、`skill_id/version`、`report_id/type` 和 `assistant_message_id`。

## 6. Events and progress

新增事件：

```text
skill.run.started   {task_id, skill_id, skill_version}
skill.run.completed {task_id, skill_id, skill_version}
skill.run.failed    {task_id, skill_id, skill_version}
report.generated    {report_id, report_type, period, source_task_id}
```

事件不包含 Prompt、Chain-of-Thought 或完整 Report。产品进度使用“正在分析消费数据”“正在生成报告”“正在保存报告”等 stage，不暴露隐藏推理。

## 7. Report API

```http
GET /api/v1/reports?conversation_id=&limit=20&offset=0
GET /api/v1/reports/{report_id}
```

列表返回轻量 metadata：月份、类型、headline、总支出展示值、scope 和创建时间；详情返回 provenance 与 typed `MonthlySpendingReport`。`limit` 约束为 `1..100`。Route 不直接执行 SQL。

## 8. Decimal JSON contract

所有 exact financial `Decimal` 由 Pydantic JSON 序列化为 string，展示值由 Backend `ReportFormatter` 提供：

```json
{
  "total_spending": "16547.30",
  "total_spending_display": "¥16,547.30",
  "percentage_change": "77.29503278618265975228217546",
  "percentage_change_display": "+77.3%"
}
```

前端不把这些值转换为 JavaScript `number`，也不重新计算金额、比例或环比。

## 9. Structured frontend

新增 `/reports` 与 `/reports/[reportId]`：

- `ReportList` 处理 loading、empty、error 和历史报告导航。
- `MonthlyReportView` 组合 Header、Overview、Period Comparison、Category Breakdown、Insights、Top Transactions 和 Data Quality。
- Overview、comparison、category 与 transaction 金额均直接使用 Backend `*_display`。
- Category 只做中文 presentation mapping，保留 Backend 英文稳定 enum。
- `PARTIAL` 报告会明确展示数据不完整和 deterministic notes。

没有引入 Chart library，也没有用 JSON dump 或 Markdown blob 代替结构化组件。

## 10. Conversation ReportCard 与 refresh recovery

Conversation Workspace 根据 Task authoritative `output.report_id` 获取 Report 资源并显示 `ReportCard`，不解析 Assistant Message。Card 展示月份、headline、总支出和“查看报告”。

SSE 收到 `report.generated` 后只触发 Task/Report resource refresh，事件 payload 不是 source of truth。浏览器刷新后，Conversation、Task 和 Report 均通过 Server Resource API 恢复。

## 11. Golden integration result

2026-08 全账户报告经持久化、GET API 和 UI 验证：

```text
total_income                 = 23800.00      (¥23,800.00)
total_spending               = 16547.30      (¥16,547.30)
previous_spending            = 9333.20       (¥9,333.20)
absolute_change              = 7214.10       (+¥7,214.10)
percentage_change            = 77.29503278618265975228217546
percentage_change_display    = +77.3%
FOOD absolute change         = 589.10
SHOPPING absolute change     = 2662.00
TRAVEL absolute change       = 4260.00
```

GET Report 的 deterministic core 与 committed `golden_monthly_report_core.json` 全等。

## 12. Real DeepSeek trace

真实 Provider 产品 smoke 的脱敏 trace：

```text
route=FINANCIAL_ANALYSIS
requested_output=MONTHLY_REPORT
agent_id=agent:financial-analysis
tools=[spending_summary, category_breakdown, compare_periods,
       top_transactions(limit=5)]
skill=skill:monthly-spending-report@1
report_persisted=true
GET_report=true
golden_core_equal=true
assistant_messages=1
assistant="2026年8月消费报告已生成。"
```

Trace 未输出 API Key、完整 Prompt 或 Chain-of-Thought。

## 13. Browser E2E

在 Docker Compose + 真实 DeepSeek 环境完成：

1. 在 Agent Workspace 输入“生成一份2026年8月份消费报告”。
2. 观察分析、生成和保存阶段。
3. 仅收到最终 Assistant confirmation，Conversation 出现 ReportCard。
4. 点击进入 Structured Report，核对 Overview、环比、分类、洞察、Top 5 和 COMPLETE。
5. 刷新详情页后 Report 仍存在。
6. `/reports` 可查看并再次打开历史报告。

最后一次验证同时确认 `TRANSPORT` 以中文“通勤”展示。

## 14. Security regression

- FinancialAnalysisAgent 仍只有 `account.list` 和四个只读 Financial Tool。
- Skill `allowed_tools=[]`。
- “生成报告，然后给张三转账”不能获得 transfer capability。
- Report API 只读且按用户隔离。
- `report.generated` 不携带完整内容或敏感信息。
- 无 raw transaction history 进入 LLM 或 Report API 列表。

## 15. Files changed

新增 Report domain/service/repository/API、migration、产品 pipeline、报告测试、真实 smoke、Reports pages/components 和 v0.3.4 文档；更新 Router、Task schema/persistence、OpenAPI generated types、Conversation resource refresh 与 SSE handling。没有新增 Agent、Skill、Financial Tool 或写操作。

## 16. Known limitations

- 当前只支持 `MONTHLY_SPENDING` report type 和 Skill version 1。
- Report 不可编辑/删除，也不支持 PDF、Excel、邮件或定时生成。
- 没有 Chart；当前使用 cards、rows 和 table。
- 当前仍是单进程 in-process Task runner/SSE 模型，没有 Outbox、Celery、Redis 或 multi-worker delivery guarantee。
- Snapshot hash 是 provenance/integrity reference，不是数字签名。
- Narrative grounding 能验证 evidence reference 与数字泄漏，但不使用第二个 LLM 对自然语言逐句做 entailment judge。

## 17. Deviations

- 没有为 Skill 创建独立 Task 或 Skill Run 数据表，遵循单 `BANKING_REQUEST` Task 决策，以事件和 Report provenance 记录 Skill execution。
- `report.generated` 与 Report/Task/Message 在同一数据库事务中持久化，事件总线通知在 commit 后发布；本轮未引入 Outbox Pattern。
- Report list 的 headline、total display 和 scope 从 immutable `content_json` 构造，未做额外 denormalization。

## 18. Architecture questions

- 多 worker 阶段是否以 transactional outbox 保证 DB event 与实时 transport 一致？
- 新 report type 增加后，是否保持显式 typed service，还是在至少出现第二种 Artifact 后再提取有限公共抽象？
- Skill version 2 出现时，历史 Artifact 的 renderer 应继续按 report version 分派，还是保持向后兼容的统一 ViewModel？
- 未来图表应继续消费 Backend authoritative display/value 字段，还是增加专门的 typed visualization projection？
