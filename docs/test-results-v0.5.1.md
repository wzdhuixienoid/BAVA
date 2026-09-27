# Test Results v0.5.1

Date: 2026-09-27 (Asia/Shanghai)

## Backend static and unit/regression tests

Commands actually executed:

```bash
cd apps/api
uv run ruff check . ../../scripts
uv run pytest -q -m 'not postgres'
uv run pytest -q
```

Final results:

```text
Ruff: PASS
pytest -m 'not postgres': 189 passed, 7 deselected
pytest: 189 passed, 7 skipped
```

## PostgreSQL migration and integration

The isolated test database name contains `test`. Migration was applied with:

```bash
cd apps/api
DATABASE_URL=postgresql+asyncpg://banking:banking@localhost:5432/banking_test \
  uv run alembic upgrade head
```

Integration command:

```bash
TEST_DATABASE_URL=postgresql+asyncpg://banking:banking@localhost:5432/banking_test \
  uv run pytest -m postgres
```

Final result:

```text
7 passed, 189 deselected
```

PostgreSQL assertions include migration revision/columns, two independent sessions competing for
one row, `FOR UPDATE SKIP LOCKED`, active-lease exclusion, expired-lease reclaim, provider accept
before local persistence, stable idempotency key, one provider row/reference/debit, terminal
schedule cleanup, and terminal claim exclusion.

## Recovery behavior coverage

Automated coverage includes:

- deterministic bounded backoff;
- due schedule eligibility and future-schedule exclusion;
- terminal Operation exclusion;
- active lease exclusion and expired lease reclaim;
- `CREATED` recovery with the original Operation/payload/key;
- provider accepted while application remains `CREATED`;
- `SUBMITTED` query-only recovery;
- `UNKNOWN` query-only recovery;
- provider query timeout/unavailability remains `UNKNOWN` and reschedules;
- attempt/last/next metadata updates;
- terminal schedule and lease cleanup;
- worker loop start/clean stop;
- manual and background paths sharing `OperationService` transitions;
- existing direct same-key ten-replay exact-once test;
- Financial Analysis, Approval/Reauthentication, Transfer, Operation, routing, runtime, and report
  regressions.

## OpenAPI and frontend

Commands actually executed:

```bash
OPENAPI_URL=http://127.0.0.1:8010/openapi.json pnpm api:generate
pnpm web:lint
pnpm web:typecheck
pnpm web:build
```

Final results:

```text
OpenAPI generation: PASS
Frontend ESLint: PASS
Frontend TypeScript: PASS
Next.js production build: PASS
```

The temporary API used the isolated `banking_test` database and disabled the automatic recovery
loop while serving OpenAPI.

## Not executed

No real DeepSeek smoke, browser E2E, or Docker image build is claimed in this delivery unless it is
added below after an actual run. Existing smoke assumptions remain regression-protected by the
unchanged LLM/Agent boundary and backend tests, but that is not presented as a fresh live-provider
result.
