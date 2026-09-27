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

Not executed. The PostgreSQL integration suite above is not described as Docker/browser E2E.
