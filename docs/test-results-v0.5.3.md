# Test Results v0.5.3

Date: 2026-09-27 (Asia/Shanghai)

## Pre-fix audit/reproduction

The v0.5.2 source contained 21 instances of:

```text
business/Event commit
then EventBus publish
```

Skipping the second call left a committed Event with no durable publication state and no restart
scanner. This was the reproducible commit-to-publish crash window. After the change, production
source contains one direct EventBus publication call, owned exclusively by `OutboxPublisher`.

## Unit and default backend validation

Commands executed during implementation:

```bash
cd apps/api
uv run ruff check . ../../scripts
uv run pytest -q -m 'not postgres'
uv run pytest -q
```

Results:

```text
Ruff: passed
non-PostgreSQL: 195 passed, 19 deselected
default pytest: 196 passed, 18 skipped
```

Unit coverage includes atomic Event/Outbox creation, forced Outbox failure rollback, no direct
double path, deterministic capped retry, temporary EventBus failure, crash-before-publish recovery,
publish-before-ack duplicate delivery, published-row exclusion, and durable/live Event identity.

## PostgreSQL migration and integration

Commands executed:

```bash
DATABASE_URL=postgresql+asyncpg://banking:banking@localhost:5432/banking_test \
  .venv/bin/alembic upgrade head

DATABASE_URL=postgresql+asyncpg://banking:banking@localhost:5432/banking_test \
  uv run alembic upgrade head

DATABASE_URL=postgresql+asyncpg://banking:banking@localhost:5432/banking_test \
  .venv/bin/alembic downgrade 0010

DATABASE_URL=postgresql+asyncpg://banking:banking@localhost:5432/banking_test \
  .venv/bin/alembic upgrade head

TEST_DATABASE_URL=postgresql+asyncpg://banking:banking@localhost:5432/banking_test \
  uv run pytest -q -m postgres
```

Results:

```text
0010 -> 0011 upgrade: passed
0011 -> 0010 downgrade: passed
0010 -> 0011 re-upgrade: passed
final `uv run` head check: passed
PostgreSQL: 19 passed, 195 deselected
```

The PostgreSQL suite uses independent sessions/connections and covers `SKIP LOCKED`, one active
owner, active-lease exclusion, expired-lease reclaim, retry, at-least-once duplicate delivery,
published exclusion, Event uniqueness, recovery-generated Operation terminal Events, and unchanged
provider exact-once debit.

## OpenAPI/frontend

The public Event/SSE/resource schema is unchanged; the API document version is now 0.5.3.

Commands executed:

```bash
pnpm api:generate
pnpm web:lint
pnpm web:typecheck
pnpm web:build
```

Results:

```text
OpenAPI client generation: passed
web lint: passed
web typecheck: passed
web production build: passed (5 routes)
```

## Docker/product smoke

A local Docker Compose crash/restart-style smoke was executed against the real API and PostgreSQL:

```bash
OUTBOX_PUBLISHER_ENABLED=false docker compose up --build --detach
curl -X POST http://localhost:8000/api/v1/conversations ...
curl -X POST http://localhost:8000/api/v1/conversations/{id}/messages ...
docker compose exec -T postgres psql -U banking -d banking -c '<task Event/Outbox counts>'
OUTBOX_PUBLISHER_ENABLED=true docker compose up --detach --force-recreate api
docker compose exec -T postgres psql -U banking -d banking -c '<task Event/Outbox counts>'
curl http://localhost:8000/health
curl http://localhost:3000
```

Observed facts:

```text
startup migration: 0010 -> 0011 passed
publisher-disabled task: 11 Events, 11 Outbox rows, 0 published
API process recreated with publisher enabled
post-restart task: 11 Events, 11 Outbox rows, 11 published, 0 unpublished
API health: HTTP 200
web root: HTTP 200
```

This smoke validates durable backlog survival and automatic publication after an API-process
restart. It is not a browser receipt/acknowledgement test and does not claim cross-process SSE
fan-out or real-provider coverage. The Compose stack was left running after validation.
