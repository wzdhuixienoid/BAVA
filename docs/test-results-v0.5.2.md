# Test Results v0.5.2

Date: 2026-09-27 (Asia/Shanghai)

## Pre-fix PostgreSQL race reproduction

A synchronized two-provider test was run before the advisory-lock implementation. Both independent
transactions read an initial 10,000 balance before either ledger insert. With different keys and
8,000 each, the old implementation returned:

```text
ACCEPTED
ACCEPTED
```

The invariant test failed at the expected one-success/one-failure assertion. This confirms the
v0.5.1 process-local lock did not provide cross-process financial safety.

The reproducer command was:

```bash
TEST_DATABASE_URL=postgresql+asyncpg://banking:banking@localhost:5432/banking_test \
  uv run pytest -q \
  tests/test_provider_concurrency.py::test_different_keys_cannot_overspend_same_account
```

Before the fix it failed because both outcomes were `ACCEPTED`. The same test passes after the
Provider transaction-level advisory lock was added.

## Backend verification

Commands actually executed:

```bash
cd apps/api
uv run ruff check . ../../scripts
uv run pytest -q -m 'not postgres'
uv run pytest -q
```

Results:

```text
ruff: all checks passed
pytest -q -m 'not postgres': 189 passed, 15 deselected
pytest -q: 190 passed, 14 skipped
```

## PostgreSQL migration and integration

The database name contains `test`. Migration command:

```bash
DATABASE_URL=postgresql+asyncpg://banking:banking@localhost:5432/banking_test \
  uv run alembic upgrade head
```

PostgreSQL command:

```bash
TEST_DATABASE_URL=postgresql+asyncpg://banking:banking@localhost:5432/banking_test \
  uv run pytest -q -m postgres
```

Results:

```text
Alembic: 0009 -> 0010 upgrade succeeded
PostgreSQL pytest: 15 passed, 189 deselected
```

The PostgreSQL suite covers different-key same-account contention, exact-fit concurrent transfers,
scheduler-independent unequal amounts, different-account independence, same-key concurrent replay,
replay after current balance reaches zero, persisted insufficient-funds replay, deterministic lock
mapping across processes, stale pre-check rejection, Provider success before Application
persistence, background recovery, SKIP LOCKED claims, lease expiry/fencing, and terminal cleanup.

## OpenAPI and frontend

The public resource fields are unchanged, but the OpenAPI document version changes to 0.5.2. A
temporary API was started against `banking_test` with Operation recovery disabled, then the client
was regenerated from that live OpenAPI document and the frontend was validated:

```bash
OPENAPI_URL=http://127.0.0.1:8010/openapi.json pnpm api:generate
pnpm web:lint
pnpm web:typecheck
pnpm web:build
```

Results:

```text
OpenAPI generation: passed
web lint: passed
web typecheck: passed
web production build: passed (5 static/dynamic routes generated)
```

## Docker/product smoke

Executed with the existing Compose deployment:

```bash
docker compose up --build --detach
```

Observed runtime checks:

```text
PostgreSQL: healthy
API startup migration: 0009 -> 0010 succeeded
GET /openapi.json: version 0.5.2
Web HTTP response: 200
```

Two complete Transfer Workflows were then prepared through the running HTTP API. Both passed
Draft, Validation, Approval, and Reauthentication while the source account still had enough funds
for either individual transfer. Their distinct Operations were committed concurrently:

```text
source account fixture balance: 23,864.52
pre-existing successful provider debit: 2,000.00
available before smoke: 21,864.52

Operation A: 12,000.00 -> SUCCEEDED
Operation B: 12,000.00 -> FAILED / INSUFFICIENT_FUNDS

successful provider debit added by smoke: 12,000.00
successful provider debit after smoke: 14,000.00
effective balance after smoke: 9,864.52
```

Both concurrent commit requests returned HTTP 200 with server-authoritative terminal Workflow and
Operation states. The Provider ledger contains one new successful 12,000 row and one new failed
12,000 row. No overspending occurred.
