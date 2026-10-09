# 历史档案：Test Results v0.4.3

> 历史材料，保留原记录日期、版本和结论。旧风险规则、待办事项、测试数量与本地部署状态不代表 v0.10.3；当前说明见 [文档导航](../../README.md)。

Date: 2026-09-25 (Asia/Shanghai)

## Backend and PostgreSQL

```text
pytest -q -m "not postgres"
182 passed, 6 deselected
```

```text
pytest -q
182 passed, 6 skipped
```

```text
TEST_DATABASE_URL=.../banking_test pytest -q -m postgres
6 passed, 181 deselected
```

PostgreSQL migration advanced from `0007` to `0008`. Integration assertions cover Operation and provider-ledger schemas, Approval `consumed_by_operation_id`, atomic CREATED recovery through new sessions, stable idempotency key, effective balance persistence, one provider row, final Workflow/Operation recovery, and ownership 404 semantics.

Operation/fault tests cover:

- SUCCESS → provider-confirmed SUCCEEDED and exactly one debit;
- DEFINITIVE_FAILURE → FAILED and zero debit;
- TIMEOUT_AFTER_ACCEPT → UNKNOWN/COMMITTING → query-only reconcile → SUCCEEDED;
- Crash A: local CREATED transaction committed before submit;
- Crash B: provider applied while local state remained CREATED;
- one idempotency key replayed ten times with one row/reference/debit;
- stale double commit and stale reconcile conflicts;
- Approval consumption and one Operation per Workflow;
- final balance change and Policy deny producing zero Operation/consumption/provider call;
- Approval/Reauthentication expiry state repair using injectable clocks;
- recovery after authorization TTL once Operation exists;
- Agent and Skill callers denied `transfer.commit`;
- frontend-safe GET response excluding payload and idempotency key.

Committed `accounts.json` and `transactions.json` were not modified.

## Static, contract, frontend, and containers

```text
Ruff check (backend, tests, scripts): PASS
OpenAPI generation: PASS
Frontend ESLint: PASS
Frontend TypeScript: PASS
Next.js production build: PASS
docker compose build api web: PASS
API startup + Alembic 0008: PASS
PostgreSQL healthcheck: PASS
Web startup: PASS
```

The generated client contains Workflow commit, safe Operation GET, and expected-version reconcile contracts. `idempotency_key` is absent from `OperationResource` and `OperationSummary`.

## Real DeepSeek smoke

`scripts/smoke_transfer_operation.py` passed against the configured real provider:

```text
provider = openai_compatible
model = deepseek-v4-flash
route = TRANSFER_WORKFLOW
recipient = 张三
payee_candidates = 2
source_account = acc_salary
workflow = SUCCEEDED
operation = SUCCEEDED
approval = CONSUMED
balance_delta = -2000.00
provider_transfer_count = 1
```

DeepSeek participated only in routing and semantic intent extraction. The output contained no API key, reauthentication secret, idempotency key, full account number, prompt dump, or reasoning trace.

## Browser E2E

Passed against rebuilt Docker API/Web/PostgreSQL services:

1. Entered “给张三转2000”.
2. UI rendered two disambiguated 张三 records.
3. Selected the first payee and 工资卡; initial displayed balance was ¥23,864.52.
4. Reached `READY_FOR_REVIEW` and clicked “确认这笔转账”.
5. Started and completed development step-up authentication.
6. Reached `READY_FOR_COMMIT`; UI explicitly warned “这一步将真正提交资金转账”.
7. Clicked “提交转账”.
8. Reached authoritative Workflow `SUCCEEDED` version 10 and rendered “转账成功” with provider reference/completion time.
9. Queried “我工资卡余额多少”; the tool-grounded response was ¥21,864.52, exactly ¥2,000.00 lower.
10. Refreshed the browser, then rebuilt/recreated the API process and refreshed again; conversation, Operation-backed `SUCCEEDED`, success details, and reduced balance response all recovered.
11. No submit or cancel action remained after Operation creation.

The browser conversation's persisted Workflow had exactly one joined Operation row; the provider ledger had exactly one successful salary-account transfer row.

The automated TIMEOUT_AFTER_ACCEPT integration verifies the UNKNOWN UI backend contract: initial UNKNOWN with one applied debit, no UNKNOWN resubmit, then status query to SUCCEEDED.

## Security and exact-once evidence

- LLM/Agent/Skill callers cannot invoke `transfer.commit`.
- Commit accepts only authoritative `operation_id` internally and no frontend financial payload.
- Approval and Reauthentication are rechecked before Operation creation.
- Application Operation creation, Approval consumption, Workflow COMMITTING, and events share one DB transaction.
- Provider calls occur after that transaction.
- Retry/restart always uses the same persisted idempotency key.
- UNKNOWN is never mapped to definitive failure and is never resubmitted.
- Provider same-key replay count: 10; provider rows/debits: 1.
- Only provider-confirmed Operation SUCCEEDED renders success.
