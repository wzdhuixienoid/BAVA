# 历史档案：Test Results v0.7.3

> 历史材料，保留原记录日期、版本和结论。旧风险规则、待办事项、测试数量与本地部署状态不代表 v0.10.3；当前说明见 [文档导航](../../README.md)。

执行日期：2026-09-28（Asia/Shanghai）

## 定向开发测试

```text
anomaly + financial agent + security guard: PASS
transfer authorization / operation / risk: PASS
subscription cancellation: PASS
```

覆盖四种确定性 anomaly rule、冷启动、多标签合并、多币种/Principal 隔离、Prompt Injection、Security Guard 计数/重置/expiry/持久化、安全控制绕过，以及 Transfer/Subscription Operation boundary 的 fail-closed 不变式。

## 最终验证

```text
backend ruff: PASS (All checks passed)
backend pytest: PASS (251 passed, 22 skipped)
PostgreSQL suite: PASS (23 passed, 250 deselected; schema revision 0015)
frontend OpenAPI generation: PASS
frontend lint: PASS
frontend typecheck: PASS
frontend build: PASS (Next.js production build, 7 routes generated)
```

PostgreSQL suite 包含两个 session 并发记录 security signal 的回归，要求最终 failure count 不丢失且阈值处确定性进入 `WRITE_LOCKED`。

## 产品 Smoke A：异常交易

使用当前配置的 OpenAI-compatible LLM（DeepSeek）执行“最近有没有异常交易？”：

```text
route: FINANCIAL_ANALYSIS
executor: agent:financial-analysis
tool: transaction.detect_anomalies
analysis_days: 30
anomaly_count: 3
transaction_ids: txn_0129, txn_0114, txn_0020
raw_transaction_history_present: false
final answer: 明确表达“值得关注”且未确认欺诈/盗刷
```

## 产品 Smoke B：Security Lock

通过真实 Workflow/Operation service 与持久化测试 fixture 验证：

```text
3 reauthentication failures / 10 min -> WRITE_LOCKED for 15 min
start-reauth / verify-reauth while locked -> SECURITY_WRITE_LOCKED
Transfer commit while locked -> 0 Operation, Approval preserved, 0 Provider calls
Subscription cancel while locked -> 0 Operation, Approval preserved, 0 Provider calls
GREEN security status / anomaly read -> available
```

本版按要求不重跑 v0.5.x crash smoke。

## Security Guard / Operation 并发 correctness 增量（2026-09-29）

本次只验证 Security Guard 与新 Operation 创建的 TOCTOU 线性化边界，未重跑 LLM smoke、异常检测开发用例、Operation Recovery crash smoke 或前端构建。

```text
SecurityGuard / Transfer authorization / Subscription targeted: PASS (20 passed)
PostgreSQL ordered race regressions: PASS (3 passed, 16 deselected)
final backend ruff: PASS (All checks passed)
final backend pytest: PASS (251 passed, 25 skipped)
final PostgreSQL suite: PASS (26 passed, 250 deselected)
```

新增真实 PostgreSQL 回归使用两个独立 session 和 `asyncio.Event` / Security Guard test hook 精确编排顺序，不依赖长 sleep：

- 第 3 次 reauthentication failure 先取得 Security user lock：Transfer prepare 返回 `SECURITY_WRITE_LOCKED`，Operation=0，Approval 未消费，Workflow 仍为 `READY_FOR_COMMIT`，Provider transfer=0。
- Transfer prepare 先取得 Security user lock：允许首个 Operation 提交，随后 signal 激活 `WRITE_LOCKED`；后续同 Workflow 的新 commit 在 Operation 检查前被 Security Guard 拒绝，Operation 总数仍为 1。
- 第 5 次 control bypass signal 先取得 Security user lock：Subscription cancel prepare 返回 `SECURITY_WRITE_LOCKED`，Operation=0，Approval 未消费，Workflow 仍为 `READY_FOR_COMMIT`，Provider cancellation=0。
