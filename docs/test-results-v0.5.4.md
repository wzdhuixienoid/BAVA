# Test Results v0.5.4

Date: 2026-09-27 (Asia/Shanghai)

## Backend static and regression validation

Commands actually executed:

```bash
cd apps/api
uv run ruff check . ../../scripts
uv run pytest -q -m 'not postgres'
uv run pytest -q
```

Results:

```text
Ruff: passed
non-PostgreSQL: 202 passed, 21 deselected
default pytest: 203 passed, 20 skipped
```

The default suite covers due/future eligibility, terminal and waiting exclusion, retry policy and
configuration validation, heartbeat renewal/loss, lifecycle start/stop, read-oriented retry,
atomic assistant/Task completion, Report uniqueness, Transfer Workflow reuse, startup
reconciliation, Operation recovery, Provider idempotency/account serialization, and Transactional
Outbox regressions.

## PostgreSQL migration validation

Commands actually executed against a database whose name contains `test`:

```bash
cd apps/api
DATABASE_URL=postgresql+asyncpg://banking:banking@localhost:5432/banking_test \
  .venv/bin/alembic upgrade 0012
DATABASE_URL=postgresql+asyncpg://banking:banking@localhost:5432/banking_test \
  .venv/bin/alembic downgrade 0011
DATABASE_URL=postgresql+asyncpg://banking:banking@localhost:5432/banking_test \
  .venv/bin/alembic upgrade 0012
DATABASE_URL=postgresql+asyncpg://banking:banking@localhost:5432/banking_test \
  uv run alembic upgrade head
```

Results:

```text
0011 -> 0012 upgrade: passed
0012 -> 0011 downgrade: passed
0011 -> 0012 re-upgrade: passed
final `uv run` head check: passed
```

Schema inspection confirmed the five Task execution fields, non-negative attempt constraint, and
partial due index.

## PostgreSQL concurrency and crash recovery

Command actually executed:

```bash
cd apps/api
TEST_DATABASE_URL=postgresql+asyncpg://banking:banking@localhost:5432/banking_test \
  uv run pytest -q -m postgres
```

Result:

```text
21 passed, 202 deselected
```

The new real-PostgreSQL cases use independent sessions and cover one-winner `SKIP LOCKED` claim,
active-lease exclusion, heartbeat renewal, expired-lease reclaim, attempt fencing, stale Worker A
rejection after Worker B reclaims, and crash-after-claim recovery to one terminal Task Event plus
one matching Outbox intent. Existing Operation recovery, exact-once provider ledger, concurrent
different-key account safety, and Outbox lease tests also passed.

## OpenAPI and frontend

Commands actually executed:

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

Task lease/owner metadata was not added to the public Task model, and client generation produced
no tracked public schema change. The first sandboxed generation attempt could not connect to the
local API (`EPERM`); the same command was rerun with local-network permission and passed.

## Docker/product smoke: normal execution

The stack was rebuilt with deliberately short test timings:

```bash
TASK_WORKER_LEASE_SECONDS=3 \
TASK_WORKER_HEARTBEAT_SECONDS=1 \
  docker compose up --build --detach
```

Observed facts from the real API, PostgreSQL, Outbox publisher, and configured DeepSeek-compatible
LLM:

```text
startup migration 0011 -> 0012: passed
TASK_WORKER_ENABLED=true, lease=3s, heartbeat=1s

Financial Analysis Task 5f04ea7c-fbc9-4e91-ab81-f597660b4a12:
  POST returned 202 before Task terminal state
  status=COMPLETED
  execution_attempts=1
  lease/schedule cleared
  assistant messages=1
  Events=29, Outbox rows=29, published=29
  2026-08 deterministic analysis snapshot present

Report Task dc32a116-fc31-4c10-837f-22bf72ed96b6:
  status=COMPLETED
  execution_attempts=1
  Reports=1
  assistant messages=1
  Events=35, Outbox rows=35, published=35
```

The first attempted crash raced with report completion and is recorded only as the successful
normal Report smoke above; it is not claimed as crash evidence.

## Docker/product smoke: hard process crash and reclaim

A second Report Task was submitted, PostgreSQL was polled until `RUNNING`, and the API container
was killed before terminal persistence:

```bash
docker compose kill api
# wait beyond the 3-second lease
docker compose up --detach api
```

Observed facts:

```text
Task: 9886e6a4-2862-4de7-adcf-1b4fd834ab8d
before kill: RUNNING, execution_attempts=1, Report=0, assistant=0
after restart: reclaimed by the new process, execution_attempts=2
final status=FAILED
final error=REPORT_NARRATIVE_VALIDATION_FAILED (retryable=false)
lease_owner/lease_expires_at/next_run_at cleared
Reports=0
assistant messages=0
Events=34, Outbox rows=34, published=34
```

This validates real process death, durable lease expiry, automatic reclaim, fenced convergence,
and no duplicate output. The reclaimed real-LLM attempt reached a deterministic narrative
grounding validation failure, so this smoke is **not** reported as a successful Report generation.
Report success/uniqueness is separately covered by the normal Docker smoke and automated retry
tests. The Compose stack was left running.

## Docker/product smoke: Transfer authorization boundary

A valid fixture Transfer intent was submitted through the real API after the crash/restart smoke:

```text
Task: 4499d1ca-0cd5-442e-b768-e5c8dc097868
Workflow: 61102b27-b339-415b-b191-c8771a177572
Task status=COMPLETED, execution_attempts=1
Task lease/schedule cleared
Workflow status=READY_FOR_REVIEW
assistant messages=1
Approvals=0
Reauthentications=0
Operations=0
matching Provider transfers=0
```

The worker continued polling after Task completion, but did not reclaim the terminal Task or
simulate approve/reauthenticate/commit actions. This product smoke validates the intended Task vs
Workflow lifetime distinction and the financial authorization boundary. An earlier exploratory
intent used a nonexistent fixture payee and correctly produced a definitive failed Workflow with
the same zero-side-effect counts; it is not used as the primary Transfer smoke evidence.

## Real LLM scope and unexecuted smoke

Real DeepSeek-compatible routing/Financial Analysis, Report generation, and Transfer intent
extraction were executed as stated above. No real transfer Provider or real reauthentication
exists, and the Docker Transfer smoke intentionally stopped at `READY_FOR_REVIEW`; no
transfer-commit smoke was claimed for v0.5.4. Transfer retry safety, Operation separation, and
financial exact-once/concurrency invariants were validated by automated unit and PostgreSQL tests.
