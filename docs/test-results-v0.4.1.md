# Test Results v0.4.1

Date: 2026-09-25 (Asia/Shanghai)

## Automated backend

```text
.venv/bin/ruff check src tests ../../scripts
PASS

.venv/bin/pytest -q
168 passed, 5 skipped
```

The five skips are PostgreSQL-marked tests in the default SQLite run; they were run separately against the isolated PostgreSQL database.

Coverage includes routing, strict extraction failure, two-payee ambiguity, unique payee resolution, missing/zero/negative/overprecision amount, no source hint, source hint, credit rejection, insufficient funds, currency mismatch, invalid IDs, optimistic conflict, ownership, cancellation, refresh persistence, events, and prompt-injection regression.

## PostgreSQL integration

```text
DATABASE_URL=postgresql+asyncpg://.../banking_test alembic upgrade head
PASS (revision 0006)

TEST_DATABASE_URL=postgresql+asyncpg://.../banking_test pytest -q -m postgres
5 passed, 168 deselected
```

Verified workflow table migration, `state_json` round trip, version increments, stale conflict, 404 ownership isolation, workflow event persistence, source Task reference, and process/session recovery.

## OpenAPI and frontend

```text
openapi-typescript current OpenAPI → temporary schema; diff committed schema
PASS (no diff)

pnpm --filter @banking/web lint
PASS

pnpm --filter @banking/web typecheck
PASS

pnpm --filter @banking/web build
PASS
```

## Real DeepSeek smoke

```text
uv run --project apps/api python scripts/smoke_transfer_draft.py
```

Result with configured `deepseek-v4-flash`:

```text
route=TRANSFER_WORKFLOW
recipient=张三
payee_candidates=2
source_account=acc_salary
status=READY_FOR_REVIEW
write_calls=0
balance_unchanged=true
transactions_unchanged=true
```

No API key, full account number, prompt dump, or chain-of-thought was emitted.

## Browser E2E

Executed in the real local web UI against Docker PostgreSQL/API/Web:

1. Created a new conversation and submitted `给张三转2000`.
2. UI displayed both masked `张三` candidates.
3. Selected `payee_001` through the Action API.
4. UI displayed three eligible accounts and backend balance snapshots; credit was absent.
5. Selected `acc_salary`.
6. UI displayed `READY_FOR_REVIEW`, CNY 2,000.00, masked account/payee data, and the not-submitted disclaimer.
7. Verified there was no confirm-transfer button.
8. Reloaded the browser.
9. UI recovered the same workflow at version 4 and `READY_FOR_REVIEW`.

PASS.

## Docker

```text
docker compose up -d --build
PASS
```

The first migration attempt exposed and then fixed duplicate PostgreSQL enum creation. The rebuilt final API applied `0005 -> 0006`, completed startup, and the PostgreSQL, API, and Web containers were all running.

## No-money-movement evidence

- Tool registry contains no transfer commit/submit/send/write capability.
- Workflow allowlist contains only three `R1_PRIVATE_READ`, `side_effect=false` capabilities.
- Fake E2E and real-provider smoke compare all mock balances before/after.
- Fake E2E and real-provider smoke compare the transaction fixture before/after.
- Security prompt injection creates at most a draft and cannot resolve a nonexistent write tool.
- No account or transaction mutation method was introduced in `MockBankService`.
