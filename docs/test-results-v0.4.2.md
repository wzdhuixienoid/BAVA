# Test Results v0.4.2

Date: 2026-09-25 (Asia/Shanghai)

## Automated backend

```text
pytest -q
172 passed, 5 skipped
```

The five skipped tests are the opt-in PostgreSQL-marked suite when `TEST_DATABASE_URL` is absent.

```text
TEST_DATABASE_URL=.../banking_test pytest -q -m postgres
5 passed, 172 deselected
```

PostgreSQL assertions include migration revision `0007`, both new tables and timestamps, canonical payload round-trip/hash, Approval/Reauthentication linkage, workflow version increments, stale action conflict, ownership hiding, `READY_FOR_COMMIT` recovery, mutation invalidation, safe events, and unchanged balances/transactions.

## Static and contract checks

```text
Ruff (changed backend/migration/test/smoke files): PASS
OpenAPI generation: PASS
Frontend ESLint: PASS
Frontend TypeScript: PASS
Next.js production build: PASS
```

The generated client includes `set-recipient-query`, `approve`, `start-reauth`, and `verify-reauth` plus safe Approval/Reauthentication summaries.

## Real DeepSeek smoke

```text
route = TRANSFER_WORKFLOW
recipient = 张三
payee_candidates = 2
source_account = acc_salary
status = READY_FOR_COMMIT
approval = APPROVED
reauth = VERIFIED
write_calls = 0
balance_unchanged = true
transactions_unchanged = true
```

No API key, provider secret, prompt dump, full account number, or reasoning trace was printed.

## Browser E2E

Passed against rebuilt Docker API/Web/PostgreSQL services:

1. Entered “给张三转2000”.
2. UI rendered two 张三 options with bank and masked account data.
3. Selected one payee and 工资卡.
4. Reached `READY_FOR_REVIEW`.
5. Clicked “确认这笔转账”.
6. Reached `REAUTH_REQUIRED` and created a challenge.
7. Completed the local development reauthentication form.
8. Reached `READY_FOR_COMMIT` and displayed “尚未提交转账”.
9. Refreshed the browser.
10. Recovered the same `READY_FOR_COMMIT` workflow at version 7.

## Container verification

```text
docker compose build api web: PASS
API startup + Alembic 0007: PASS
Web startup: PASS
PostgreSQL healthcheck: PASS
```

## Security and zero-write evidence

- Chat text “确认，就这个” did not approve the workflow.
- Wrong reauthentication values increment attempts; the third marks the challenge failed; a new challenge is allowed.
- Injectable-clock tests cover Approval and Reauthentication expiry without sleeping.
- Verification values are absent from Workflow JSON, API summaries, Approval payloads, and Event payloads.
- Changing the approved/verified amount from 2000 to 20000 invalidates both resources and changes the hash.
- Registry contains only `payee.search`, `account.list`, and `account.get_balance` for the transfer workflow.
- Transfer write calls: **0**.
- Balance mutations: **0**.
- Transaction mutations: **0**.
