# 历史档案：Test Results v0.7.2

> 历史材料，保留原记录日期、版本和结论。旧风险规则、待办事项、测试数量与本地部署状态不代表 v0.10.3；当前说明见 [文档导航](../../README.md)。

执行日期：2026-09-28（Asia/Shanghai）

## 定向开发测试

订阅与 v0.7.1 边界定向集已通过，覆盖 detector、snapshot、API/Principal、Tool authority、Workflow/Approval/Operation/Provider、幂等、crash recovery、Prompt Injection、非 CNY fail closed 与跨日 exposure。

## 最终验证

```text
backend ruff: PASS (All checks passed)
backend pytest: PASS (238 passed, 21 skipped)
PostgreSQL suite: PASS (22 passed, 237 deselected; schema revision 0014)
frontend lint: PASS
frontend typecheck: PASS
frontend build: PASS (Next.js production build, /subscriptions generated)
```

OpenAPI client 在 API 实现完成后生成一次，已包含 Subscription domain API、统一 Workflow action 与 `SUBSCRIPTION_CANCEL` operation type。

## 产品 Smoke

### Smoke A：订阅分析

通过真实 HTTP API 和当前配置的 LLM 发送“我有哪些订阅？最近有没有涨价的？”：

```text
route/executor: agent:subscription-analysis
task: COMPLETED
tool calls: 1
SubscriptionAnalysisSnapshot: present
raw full transaction history: absent
```

### Smoke B：取消订阅

通过真实 HTTP API 和当前配置的 LLM 发送“取消星幕视频”：

```text
route/executor: SUBSCRIPTION_CANCEL / workflow:subscription-cancel
initial workflow: READY_FOR_REVIEW
risk: YELLOW
after approval: READY_FOR_COMMIT
final workflow: SUCCEEDED
operation: SUCCEEDED
subscription status: CANCELLED
reauthentications: 0
provider cancellation facts: 1
```

本版不重跑 v0.5.x 历史 Docker crash smoke。
