# 历史档案：Implementation Report v0.5.3

> 历史材料，保留原记录日期、版本和结论。旧风险规则、待办事项、测试数量与本地部署状态不代表 v0.10.3；当前说明见 [文档导航](../../README.md)。

## Outcome

v0.5.3 adds a PostgreSQL Transactional Outbox for every persisted Application Event that enters
the realtime publication path. Business state, immutable Event history, and one publication intent
now commit atomically. A dedicated multi-process-safe `OutboxPublisher` eventually hands the same
durable Event envelope to the existing process-local `EventBus` with at-least-once semantics.

Financial Analysis, Transfer, Operation recovery, provider idempotency, and account serialization
are unchanged. PostgreSQL Resource state remains authoritative; EventBus and SSE remain
notifications.

## 1. Pre-fix crash window and Event audit

Before this release, `EventPublisher.persist()` inserted an Event in the business session. Every
producer then followed the same pattern:

```text
mutate business resource
persist Event
COMMIT
publish_persisted() to process-local EventBus
```

There were 21 post-commit direct-publication call sites. A process crash between commit and
`publish_persisted()` left correct business state and durable Event history but permanently lost
the realtime notification. There was no durable publication bookkeeping or restart recovery.

The audited persisted production paths are:

- Conversation intake: `conversation.message.created`, `task.created`;
- Task lifecycle: created, started, progress, completed, failed, interrupted;
- routing/Agent/runtime/tool events supplied through the runtime event sink;
- Skill started/completed/failed and `report.generated`;
- Workflow creation and every existing workflow state transition;
- Approval creation/approval/invalidation/expiry;
- Reauthentication challenge/verification/failure/expiry/invalidation;
- Operation creation/submission/unknown/success/failure;
- Task startup reconciliation and Operation recovery transitions.

Every item above was already a durable Event and was followed by EventBus publication, so every
one now gets an Outbox intent. Ordinary logs, worker diagnostics, provider serialization logs, and
lease logs are not product Events and do not enter Outbox. No new domain events were invented.

All audited Event inserts were already in the same session as their associated business mutation.
The defect was the post-commit live publication step, not Event persistence. Direct uses of
`EventRepository` in production remain read-only except for the single centralized writer.

## 2. Event and Outbox responsibilities

```text
Event
= immutable historical/product fact and public Event API/SSE envelope

Outbox
= internal durable intent to hand that Event to realtime publication infrastructure
```

`GET /tasks/{task_id}/events` continues to read `events`. Public APIs do not expose Outbox rows.
Outbox transport metadata does not alter the Event or SSE schema.

The Outbox references `event_id`; it does not copy event type, conversation, task, sequence, or
payload. The existing Event row already contains the complete publication envelope. Referencing it
avoids two payload copies diverging and preserves the original Event identity on every retry.

## 3. Schema and migration

Migration 0011 creates `outbox_events` with:

```text
id UUID primary key
event_id UUID foreign key -> events.id, UNIQUE
created_at
published_at nullable
publish_attempts >= 0
next_publish_at nullable
lease_owner nullable
lease_expires_at nullable
last_error_code nullable
```

`UNIQUE(event_id)` is the database invariant enforcing one intent per durable Event. A partial
PostgreSQL due index covers `next_publish_at`, `lease_expires_at`, and `created_at` where
`published_at IS NULL`, matching the publisher scan without adding a generic index abstraction.

Historical Events are deliberately not backfilled. They remain durable history, but deployment of
v0.5.3 does not replay the entire old Event table as current realtime notifications. Only Events
created through the v0.5.3 writer receive Outbox rows.

Published rows are retained for audit/debugging. Cleanup and archival are deferred; there is no
correctness-sensitive deletion job in this release.

## 4. Atomic transaction boundary

The existing `EventPublisher.persist()` is now the single small persistence primitive:

```text
EventRepository.create(...)
OutboxRepository.enqueue(event_id=event.event_id)
```

Both flush through the caller's existing business `AsyncSession`; the caller commits only after
both succeed:

```text
BEGIN
business state mutation
Event insert
Outbox insert
COMMIT
```

An injected Outbox insertion failure rolls back Message, Task, Event, and Outbox together. An
Outbox constraint/flush failure therefore cannot leave a successfully committed business Event
without durable publication intent. Operation/Workflow terminal transitions keep their existing
atomic transaction and simply gain two matching Outbox rows.

## 5. Removal of the old double path

All 21 `publish_persisted()` calls were removed and that method no longer exists. A repository
audit leaves exactly one production `EventBus.publish()` call: inside `OutboxPublisher`.

There are no current ephemeral non-persisted product notifications requiring a direct path.
Normal no-failure delivery is therefore one Event, one Outbox row, and one EventBus publication.
Duplicates arise only from the documented at-least-once crash window.

## 6. Publisher claim, lease, and fencing

Each API process may run an `OutboxPublisher`. A short claim transaction selects rows satisfying:

```text
published_at IS NULL
next_publish_at <= now
lease absent or expired
ORDER BY next_publish_at, created_at, outbox_id
FOR UPDATE SKIP LOCKED
LIMIT batch_size
```

The transaction writes a process-unique owner, lease expiry, and increments `publish_attempts`,
then commits. The Event is loaded and EventBus is called after the row lock transaction ends.

Success/retry writeback requires the same owner, an unexpired lease, and unpublished state. A stale
publisher cannot mark or reschedule a row reclaimed by another process. If a process dies, it does
not need graceful unlock; lease expiry makes the row reclaimable.

Batch claims are immediately dispatched through `asyncio.gather`, rather than being published
sequentially. Later batch entries therefore start without waiting behind earlier EventBus calls.
The configured lease must still exceed normal local EventBus latency; fencing prevents stale
writeback if it does not.

## 7. Retry and poison-event behavior

The dedicated `OutboxPublicationPolicy` implements deterministic exponential delay:

```text
initial delay -> multiply per attempt -> cap at maximum delay
```

Settings control enabled state, polling, lease, initial/max retry, multiplier, and batch size.
A temporary publication exception leaves `published_at` null, stores
`EVENT_BUS_PUBLISH_FAILED`, clears the lease, and schedules the next due time. Business state is
never rolled back or modified.

Potential poison Events remain unpublished and retry at the capped delay. They are logged with
bounded identifiers and persistent error state; this release does not falsely mark them published
or add a Dead Letter Queue.

## 8. At-least-once semantics

`published_at` means only that one publisher successfully returned from the current EventBus and
durably acknowledged that handoff. It does not mean every browser received, acknowledged, or saw
the notification.

The unavoidable window is explicit:

```text
EventBus.publish succeeds
process dies before mark-published transaction
lease expires
same Outbox/Event is reclaimed and published again
```

Tests prove the same `event_id` may be observed twice while Event count, Outbox count, Conversation
state, Operation state, Approval consumption, provider row, provider reference, and debit remain
unchanged. Duplicate notification is allowed; duplicate business side effects are not.

## 9. Operation recovery integration

Operation recovery still calls `OperationService`, whose terminal Operation and Workflow updates,
Events, and Outbox intents share one transaction. The worker never publishes or executes Outbox
itself. The Outbox publisher later delivers `operation.succeeded` and `workflow.succeeded` without
calling transfer tools or the Provider.

The integration test models provider success followed by an Application crash, then Operation
recovery. It asserts the recovery-generated terminal Event has a matching Outbox, is published,
and publisher attempts leave the provider transfer/debit count unchanged.

## 10. Ordering and public contracts

Claim order is stable for predictability, and Event `sequence` remains the durable global ordering
field. Concurrent publishers plus at-least-once delivery do not promise strict global delivery
order. The current frontend treats SSE as a refresh hint and reloads authoritative resources; it
does not compute business state from notification order.

The Event domain model, task Event API, SSE fields, and frontend event types are unchanged. Tests
confirm the Event IDs returned by the durable Task Event API are the same IDs published live.

## 11. Lifecycle and observability

FastAPI lifespan starts the Operation recovery worker and the independent Outbox publisher after
checkpoint setup and stale Task reconciliation. Shutdown stops each loop cleanly; process-kill
correctness relies on durable lease expiry, not shutdown callbacks.

Bounded logs cover publisher start/stop, claim/reclaim, attempt, success, failure, retry scheduling,
and lease loss with `outbox_id`, `event_id`, attempt, and event type where available. They exclude
Event payloads, credentials, API keys, reauthentication secrets, and banking verification input.

## 12. PostgreSQL verification

Real PostgreSQL tests prove:

- Event + Outbox commit together and Event uniqueness rejects a second intent;
- committed unpublished rows are recovered without user action;
- two independent sessions use `SKIP LOCKED`, giving one active owner;
- an active lease excludes another publisher and an expired lease is reclaimable;
- EventBus failure schedules retry and later success marks published;
- publish-before-ack crash republishes the same Event exactly as at-least-once permits;
- published rows are excluded from future scans;
- Operation recovery terminal Events are delivered without another provider debit;
- all v0.5.1/v0.5.2 recovery, idempotency, and account-concurrency regressions remain intact.

A Docker Compose crash/restart-style product smoke additionally started the API with publication
disabled, created a real task, and observed 11 committed Events with 11 unpublished Outbox intents.
After recreating the API process with publication enabled, the same 11 intents became published
with no missing rows; API and web health checks both returned HTTP 200. This verifies restart
discovery in the packaged runtime without claiming browser acknowledgement or cross-process SSE
fan-out.

## 13. Scope and remaining limitations

No Kafka, Redis, Celery, generic worker/queue/scheduler, event sourcing, CQRS, exactly-once
messaging, LISTEN/NOTIFY, DLQ, client acknowledgement, or SSE replay protocol was introduced.
`OperationRecoveryWorker` and `OutboxPublisher` remain separate explicit components.

EventBus is still process-local. PostgreSQL guarantees that some publisher process eventually
hands the Event to its local bus, but a client connected to API Process B is not guaranteed to see
an Event published by Process A. This release does not claim cross-process realtime fan-out.
Resource APIs remain the recovery path and source of truth.

Other limitations include retained published Outbox growth without archival, API-process-hosted
publisher deployment, no distributed metrics/tracing, no client delivery acknowledgement, no
real transfer/reauthentication provider, and no generic durable Task worker.
