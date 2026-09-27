# Implementation Report v0.5.1

## Outcome

v0.5.1 upgrades persisted Transfer Operations from manual recovery to automatic,
PostgreSQL-coordinated recovery. Every API process may run one small recovery loop, while
`FOR UPDATE SKIP LOCKED`, durable leases, stable idempotency keys, and optimistic state updates
ensure that one due Operation is actively owned by at most one worker during a valid lease.

Financial Analysis and Transfer remain complete vertical slices. No Agent, Planner, queue,
generic scheduler, or generic execution framework was added.

## 1. Operation schema

Migration `0009_operation_recovery.py` adds:

```text
next_reconcile_at    timestamptz nullable
reconcile_attempts   integer not null default 0, CHECK >= 0
last_reconcile_at    timestamptz nullable
lease_owner          varchar(255) nullable
lease_expires_at     timestamptz nullable
```

It also adds the partial recovery index
`ix_operations_recovery_due(status, next_reconcile_at, lease_expires_at)` for
`CREATED / SUBMITTED / UNKNOWN`. Existing non-terminal rows are backfilled with
`next_reconcile_at = CURRENT_TIMESTAMP`, so an upgrade from 0008 does not strand them. Existing
terminal rows remain unscheduled.

New Operations are created with `reconcile_attempts = 0` and an immediately due
`next_reconcile_at`. Terminal transitions clear `next_reconcile_at`, `lease_owner`, and
`lease_expires_at`.

## 2. Eligibility and discovery

`OperationRepository.claim_due()` considers only:

```text
status IN (CREATED, SUBMITTED, UNKNOWN)
AND (next_reconcile_at IS NULL OR next_reconcile_at <= now)
AND (lease_expires_at IS NULL OR lease_expires_at <= now)
```

`NULL next_reconcile_at` is treated as due for backward safety. `SUCCEEDED` and `FAILED` are
never eligible. Selection is ordered by schedule and creation time and bounded by the configured
batch size; the partial index prevents a full-table terminal-row scan.

## 3. PostgreSQL claim and multi-process safety

The claim transaction executes `SELECT ... FOR UPDATE SKIP LOCKED`, writes the worker-instance
identifier and lease expiry, flushes, and commits. A second independent session skips a row while
the first session holds its lock; after commit it also excludes the row because the lease is
active.

The lease owner is a per-process value containing host, PID, and a random UUID. State persistence
requires all of the following:

```text
same operation_id
same lease_owner
lease_expires_at > now
same Operation version
```

This acts as a fencing condition. A stale worker cannot persist after another worker has
reclaimed the row. Manual reconciliation uses the same claim and lease rules with a unique
`manual:<uuid>` owner.

## 4. Short transactions and provider I/O

The execution shape is:

```text
TX 1: lock eligible row -> persist lease -> COMMIT
no DB transaction: submit/query provider
TX 2: lock claimed Operation and Workflow -> persist transitions/events/schedule -> COMMIT
```

For `CREATED`, an accepted submission may produce a short intermediate `SUBMITTED` transaction,
then the provider status query occurs with no transaction open, followed by another short result
transaction. The retained lease is renewed at that intermediate boundary.

This is a deliberate refinement of the v0.4.3 code. The v0.4.3 report correctly stated that the
provider call happened after the atomic Operation-creation transaction committed, but the old
reconcile method opened a new SQLAlchemy read transaction before provider I/O and kept that
transaction until the transition commit. It did not hold a row lock, but v0.5.1 now closes even
that read transaction explicitly before network I/O.

## 5. Lease crash recovery

If a worker dies after claim, its lease remains durable. No permanent ownership exists. After
`lease_expires_at`, another worker may claim the row and records it as a reclaim in logs. If a
worker loses or outlives its valid lease, the owner/expiry/version fencing check prevents stale
state persistence.

If the crash happened after provider acceptance but before application persistence, the next
worker sees the original application status and uses the original persisted idempotency key.
Mock Provider uniqueness returns the existing transfer, so recovery does not create a second
debit.

## 6. CREATED recovery

`CREATED` is already the durable authorization boundary: the Approval is consumed, Workflow is
`COMMITTING`, final checks passed, and immutable payload/hash/key are stored. Recovery therefore
submits that exact Operation through the existing `operation_id`-only tool path. It never creates
another Operation, Approval, Reauthentication, payload, or idempotency key.

An ambiguous submit becomes `UNKNOWN` and is scheduled. An accepted submit becomes `SUBMITTED`
and is queried. A definitive provider rejection becomes `FAILED`. Authorization TTL is not
rechecked after Operation creation.

## 7. SUBMITTED recovery

`SUBMITTED` calls only `transfer.get_status`. Terminal provider success/failure becomes
`SUCCEEDED`/`FAILED`; pending remains `SUBMITTED`; an inconclusive or unavailable query becomes
or remains `UNKNOWN` and is scheduled again. Temporary unavailability is not business failure.

## 8. UNKNOWN query-only safety

`UNKNOWN` calls only `transfer.get_status`. The state dispatcher has no path from `UNKNOWN` to
provider submission. Query timeout, unavailable provider, missing result, or inconclusive status
keeps the Operation non-terminal and schedules another attempt. This preserves the rule:

```text
Timeout != FAILED
UNKNOWN -> query original Operation status
```

## 9. Stable idempotency and exact-once mock debit

The worker accepts only a claimed `operation_id`. Tool handlers reload the authoritative
Operation and its immutable `payload_json` and `idempotency_key`. No recovery code can supply or
replace financial fields. Database uniqueness remains enforced on both application Operation key
and Mock Provider ledger key.

Automated SQLite and PostgreSQL tests simulate provider acceptance while the application row is
still `CREATED`, then recover after lease expiry. They assert one provider row/reference, one
effective debit, the same key, and terminal success. Repeated direct provider replay coverage from
v0.4.3 also remains passing.

## 10. Shared manual and background semantics

Both paths call `OperationService`:

```text
POST /operations/{id}/actions/reconcile
        -> OperationService.reconcile() -> claim -> reconcile_claimed()

OperationRecoveryWorker
        -> repository batch claim -> OperationService.reconcile_claimed()
```

The same submission/query dispatch, provider result mapping, Operation transition, Workflow
transition, completion timestamps, versions, events, retry metadata, and terminal cleanup are
therefore used by both paths. There is no second reconciliation implementation.

## 11. Worker lifecycle and configuration

FastAPI lifespan starts the worker after checkpoint setup and stale Task reconciliation, and stops
it on shutdown. Every API process may run a worker. Correctness depends on PostgreSQL, not a
process-local mutex.

Configuration uses the existing Settings/environment style:

```text
OPERATION_RECOVERY_ENABLED
OPERATION_RECOVERY_POLL_INTERVAL_SECONDS
OPERATION_RECOVERY_LEASE_SECONDS
OPERATION_RECOVERY_INITIAL_RETRY_SECONDS
OPERATION_RECOVERY_MAX_RETRY_SECONDS
OPERATION_RECOVERY_BACKOFF_MULTIPLIER
OPERATION_RECOVERY_BATCH_SIZE
```

The enable switch lets tests/scripts/environments opt out. Tests inject millisecond retry and
short lease values without sleeping for production intervals.

## 12. Retry scheduling

Every completed reconciliation attempt increments `reconcile_attempts`, writes
`last_reconcile_at`, and either clears scheduling for a terminal state or computes:

```text
min(initial_delay * multiplier ** (attempt - 1), maximum_delay)
```

There is no tight retry loop. A `CREATED -> SUBMITTED -> query` sequence counts as one logical
attempt; the intermediate accepted-submission transition retains and renews the lease, while the
query result finalizes attempt metadata.

## 13. State propagation and events

The existing authoritative transition is reused:

```text
Operation SUCCEEDED -> Workflow SUCCEEDED
Operation FAILED    -> Workflow FAILED
otherwise           -> Workflow COMMITTING
```

Operation/Workflow versions, timestamps, provider reference, safe error fields, persisted Events,
and process-local publication follow the v0.4.3 rules. Only `Operation SUCCEEDED` can produce the
product success state.

Logging covers worker start/stop, claim/reclaim, attempt, terminal result, non-terminal schedule,
lease loss, scan/reconciliation exception, and unavailable provider submission/status query. It
does not include payload, idempotency key, credentials, or reauthentication input.

## 14. Verification of multi-process safety

The PostgreSQL integration test uses two independent `AsyncSession` instances. Session A claims
and deliberately holds the row lock; Session B executes the same claim and receives no row via
`SKIP LOCKED`. After A commits, B still receives none during the active lease. Advancing the claim
time beyond lease expiry lets B reclaim. The test then completes recovery and proves exact-once
provider facts.

## 15. Events and the deferred Outbox

This version continues to persist current events and publish them after commit. A process can
still crash after the business transaction commits but before publication, so realtime delivery
may be lost. Resource APIs and PostgreSQL remain authoritative. Transactional Outbox is explicitly
deferred to 05.2; implementing part of it here would create a second reliability mechanism without
completing its delivery contract.

## 16. Scope boundary and remaining limitations

This version does not solve two different Operations concurrently spending the same account.
Provider-side per-account serialization remains process-local, and there is no database account
lock or balance reservation. That is the separate 05.3 cross-process financial concurrency
problem, not same-Operation idempotency.

It also does not implement 05.4 durable generic task/worker execution. The new loop is deliberately
specific to Operation reconciliation.

Remaining production reliability limitations include:

- no Transactional Outbox; committed event publication can be lost;
- no cross-process account-level financial serialization or reservation;
- API-process-hosted worker rather than an independently scalable worker deployment;
- no lease heartbeat during a single provider call (the configured lease must exceed the normal
  provider timeout; stale completion is fenced and a later retry remains safe);
- no real transfer provider or real reauthentication provider;
- no reversal/refund, scheduled transfer, FX, or post-submit cancellation;
- Mock Provider and application tables share one PostgreSQL deployment for this teaching system.

No `transfer.commit` caller permission was expanded. It remains
`allowed_callers = ["workflow:transfer"]`; the worker can only resume a claimed existing Operation
through `OperationService` and cannot construct arbitrary transfers.
