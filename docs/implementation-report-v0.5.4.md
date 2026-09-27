# Implementation Report v0.5.4

Date: 2026-09-27 (Asia/Shanghai)

## 1. Scope and pre-v0.5.4 crash gap

v0.5.3 durably stored a Task before execution, but the HTTP process immediately launched
`InProcessTaskRunner` through a request-local FastAPI background callback. PostgreSQL recorded Task
state, but it did not decide which process owned execution. A process crash after `RUNNING` could
only be handled by startup reconciliation, which changed stale state rather than reclaiming and
continuing the Task. There was no Task lease, expiry, heartbeat, or stale-owner fencing.

v0.5.4 makes the Task row the execution authority. The message request commits and returns; any API
process with the dedicated Task worker may claim the Task and execute it. This is deliberately
separate from Operation recovery and Outbox publication.

## 2. Audited Task state machine

The existing states were retained:

```text
PENDING
RUNNING
INTERRUPTED
WAITING_USER
WAITING_EXTERNAL
COMPLETED
FAILED
CANCELLED
SKIPPED
```

`COMPLETED`, `FAILED`, `CANCELLED`, and `SKIPPED` are terminal. `WAITING_USER` and
`WAITING_EXTERNAL` are explicitly non-runnable. A Transfer message Task currently ends after it
creates or projects a Workflow; Workflow states such as `WAITING_FOR_INPUT`, approval, and
reauthentication remain Workflow-owned and are advanced only through the existing Workflow APIs.

Runnable states are `PENDING`, `RUNNING`, and `INTERRUPTED`, but only when `next_run_at` is due and
there is no live lease. `INTERRUPTED` is scheduled only for an explicitly retryable system/runtime
failure. A historical non-retryable `INTERRUPTED` row is not made due by migration.

## 3. Previous runner and durable input audit

Previously the message handler persisted `Message + Task + Event + Outbox`, then scheduled
`runner.run(task_id)` in its own process. `InProcessTaskRunner` already contained the correct
RequestRouter, AgentRegistry, Agent runtime, Skill, Report, and Transfer Workflow dispatch logic,
so that logic was retained as the executor rather than duplicated in the worker.

The durable Task input already contains `conversation_id` and the source `message_id`. Recovery
reloads the Message, Conversation, persisted route, runtime backend, and domain resources from
PostgreSQL; it does not depend on the original HTTP body, closure, or in-memory callback.

## 4. Task schema and migration

Migration `0012_durable_task_execution.py` adds:

```text
next_run_at
execution_attempts >= 0
last_attempt_at
lease_owner
lease_expires_at
```

It also adds partial due index `ix_tasks_execution_due` over
`(status, next_run_at, lease_expires_at)` for `PENDING`, `RUNNING`, and `INTERRUPTED`.

Backfill behavior is deliberately bounded:

- historical `PENDING` and `RUNNING` Tasks become due and have no lease;
- `INTERRUPTED` becomes due only when `error_json.retryable == true`;
- waiting and terminal Tasks stay unscheduled;
- the migration does not rerun every historical non-terminal Task.

The five fields are infrastructure metadata and are not exposed by the public Task response model.

## 5. Claim, lease, attempt, and fencing semantics

`TaskRepository.claim_due()` performs a short PostgreSQL transaction:

```text
SELECT eligible tasks
ORDER BY next_run_at, created_at, id
FOR UPDATE SKIP LOCKED
LIMIT n

set status = RUNNING
set lease_owner / lease_expires_at
set last_attempt_at
increment execution_attempts and version
commit Task + task.started/progress Event + Outbox
```

The worker identity is `hostname:pid:random-uuid`. One claim is one logical execution attempt;
router, Agent, Tool, and Skill substeps do not increment `execution_attempts`.

The row lock ends at claim commit. LLM, Tool, Skill, and Workflow work happens without a long-held
database row lock. Every authoritative executor transaction reloads the Task through
`get_owned(task_id, lease_owner, execution_attempts, lease_expires_at > now)` and, for writes,
locks that row briefly. The monotonic attempt number is the fencing token. Even if an owner string
were reused, an older attempt cannot write after a later claim.

## 6. Heartbeat and lease loss

Long Agent calls cannot rely on an arbitrarily long initial lease. A per-attempt heartbeat renews
the lease in short transactions only while all of these remain true:

```text
Task is RUNNING
lease_owner matches
execution_attempts matches
current lease has not expired
```

`TASK_WORKER_HEARTBEAT_SECONDS < TASK_WORKER_LEASE_SECONDS` is validated at configuration load.
If renewal fails, the worker cancels the cooperative executor. Already-issued LLM or read-only
calls may not be physically retractable, but every later progress/event/output/terminal write is
fenced and therefore rejected. The expired Task can then be reclaimed by a new owner.

## 7. HTTP decoupling and lifecycle

The message endpoint no longer uses `BackgroundTasks`, `asyncio.create_task`, or `runner.run`.
Its transaction persists the user Message, due Task, Event, and Outbox and then returns HTTP 202.
The endpoint still reads the configured runtime backend from the executor dependency; it does not
start execution.

FastAPI lifespan now starts and stops three independent components:

```text
TaskExecutionWorker
OperationRecoveryWorker
OutboxPublisher
```

Every API process may host all three. PostgreSQL, not a process-local lock or single-process
deployment assumption, provides correctness.

## 8. Execution dispatcher and batch behavior

`TaskExecutionWorker` owns scan, claim, heartbeat, local concurrency, and lease-loss handling. It
delegates one valid `TaskExecutionClaim` to the existing `InProcessTaskRunner.execute_claimed()`.
The runner continues to use the real Router, Agent/Skill registries, LangGraph/Manual runtime,
Report service, and Transfer Workflow engine.

The claimed batch is capped to `min(batch_size, max_concurrency)` and every claim is dispatched
immediately with its own heartbeat. It does not claim many long LLM Tasks and process them
sequentially. Poll interval, batch, and local concurrency are only backpressure controls; they are
not distributed ownership primitives.

The retained `runner.run(task_id)` is a test/compatibility entry point. It creates a one-shot
`TaskExecutionWorker` and uses the same PostgreSQL claim path; it cannot bypass durable ownership.

## 9. Retry and error classification

`TaskExecutionPolicy` provides deterministic exponential backoff with initial and maximum delay.
A real retryable `AgentRuntimeError` (for example a temporary provider/LLM outage) transitions the
Task to `INTERRUPTED`, clears the lease, and sets a future `next_run_at`. Deterministic routing,
input, authorization/business, invalid model output, Skill validation, and persistence errors
retain terminal failure semantics and are not retried forever.

Terminal and waiting transitions clear `next_run_at`, `lease_owner`, and `lease_expires_at`, so they
cannot be reclaimed. A process/DB crash before a classified write simply leaves the current lease
to expire.

## 10. LangGraph responsibility

LangGraph checkpoint state remains Agent runtime progress only. Task PostgreSQL fields decide
ownership, schedule, attempt, and terminal state. A reclaimed attempt may reuse checkpoint data,
but every Application write still requires the current Task fence. The presence of a LangGraph
checkpoint is never treated as proof of lease ownership.

## 11. Read-oriented Agent recovery

Financial Analysis may safely be re-executed after a crash. The persisted Task route is reused, so
recovery does not depend on rerouting to the same executor. The final assistant Message, Task
output/status, Task Events, and Outbox intents are committed together under the current Task row
lock and fence. A crash before that commit leaves none of those final writes; a crash after it
leaves a terminal Task that cannot be claimed again.

This is at-least-once execution attempt plus fenced authoritative completion, not exactly-once LLM
execution.

## 12. Report and assistant-output idempotency

Reports already had database uniqueness on
`(source_task_id, report_type, report_version)`, and `ReportRepository.create_or_get()` restores the
existing Artifact on replay. v0.5.4 keeps that invariant.

More importantly, Report creation, assistant Message creation, Task completion, Events, and Outbox
intents are in one fenced database transaction. Ordinary Agent and Transfer final assistant
Messages follow the same atomic final-write pattern. Therefore there is no committed assistant or
Report followed by an uncommitted Task terminal state in these paths. Regression tests confirm a
terminal Task cannot be rerun and the same Report Task has one Report and one assistant output.

## 13. Transfer Task safety

Transfer Task retry first reloads a Workflow by the database-unique `source_task_id`. If it exists,
the executor projects that same Workflow and does not rerun intent extraction or create another
Workflow. It does not approve, reauthenticate, commit, call a Provider, or recover an Operation.

Consequently Task retry cannot create a second Approval, Reauthentication, Operation,
idempotency key, Provider transfer, or debit. A Transfer message Task completes after establishing
the Workflow resource; the user advances Workflow actions through the existing APIs. If an
Operation already exists, `OperationRecoveryWorker` remains its only automatic recovery owner.

## 14. Dedicated reliability boundaries

The three leased loops were intentionally not generalized:

- `TaskExecutionWorker` owns Application Task execution;
- `OperationRecoveryWorker` owns persisted financial side-effect convergence;
- `OutboxPublisher` owns Event publication delivery.

Task lease does not replace Tool/domain idempotency, Provider ledger uniqueness, account
serialization, or Operation recovery. Task-generated product Events use `EventPublisher` so Event
and one Outbox row commit together. The only production `EventBus.publish()` remains inside
`OutboxPublisher`.

## 15. Startup reconciliation change

Startup reconciliation no longer converts all `PENDING`/`RUNNING` Tasks to `INTERRUPTED` or emits
a competing terminal/interruption decision. It only supplies `next_run_at` for legacy recoverable
rows that lack a schedule. Status and retry classification remain intact; the normal worker then
claims through the same lease protocol.

## 16. PostgreSQL and recovery proof

Real PostgreSQL tests use independent `AsyncSession` instances to prove:

- two workers racing one due Task produce one claim;
- a live lease excludes the second worker;
- heartbeat renewal keeps a Task owned beyond its original expiry;
- lease expiry permits a later attempt to reclaim;
- Worker A is fenced after Worker B increments the attempt;
- crash-after-claim followed by expiry lets Worker B complete the same Task;
- completion produces one durable `task.completed` Event and matching Outbox intent.

Unit/integration coverage additionally proves due/future eligibility, waiting and terminal
exclusion, bounded retry, lease-loss cancellation, lifecycle start/stop, read-oriented retry,
Report/output deduplication, and Transfer Workflow reuse without financial side effects.

## 17. Why no broker or generic worker framework

The requirement is one explicit Task resource and one Modular Monolith worker. PostgreSQL already
provides durable schedule, lock skipping, lease storage, and transactional fencing. Celery, Redis,
Kafka, a GenericJob table, GenericLeaseWorker, priority queue, or scheduler framework would add
another state authority without solving a present requirement. No such component was introduced.

## 18. Remaining production limitations

- Task workers are still hosted inside API processes; there is no independent worker deployment.
- Delivery is at-least-once execution attempt, not exactly-once external execution.
- There is no global/per-conversation ordering contract, priority queue, Task DAG, or admin retry API.
- Cooperative cancellation cannot retract an already-sent external/LLM request; fencing prevents
  its stale result from becoming authoritative.
- EventBus/SSE fan-out remains process-local; Resource APIs remain authoritative.
- No Outbox DLQ, archival/cleanup, client acknowledgement/replay, or distributed metrics/tracing.
- Mock reauthentication and transfer providers are not production providers.
- No balance reservation/hold/capture, FX, scheduled/recurring transfer, or refund/reversal.
- No Planner, RAG, MCP, Memory, Agent-to-Agent, Celery, Redis, or Kafka.

