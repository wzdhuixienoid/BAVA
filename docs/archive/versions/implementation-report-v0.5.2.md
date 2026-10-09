# 历史档案：Implementation Report v0.5.2

> 历史材料，保留原记录日期、版本和结论。旧风险规则、待办事项、测试数量与本地部署状态不代表 v0.10.3；当前说明见 [文档导航](../../README.md)。

## Outcome

v0.5.2 makes the Mock Transfer Provider the final cross-process financial correctness boundary.
Different Operations with different idempotency keys can no longer concurrently spend the same
fixture-backed source account below zero. PostgreSQL serializes only the provider decision
transaction for that source account; the transaction recomputes authoritative effective balance
and atomically persists either a successful debit fact or a definitive rejection fact.

Financial Analysis, Transfer, and Durable Operation Recovery remain complete. No Agent permission,
Workflow authorization boundary, or public API was expanded.

## 1. Race remaining after v0.5.1

v0.5.1 guaranteed same-Operation recovery safety: one stable key, one provider row, one debit.
However, each `MockTransferProvider` instance used its own `asyncio.Lock`. Two API processes had
different lock objects, so two different keys could both read the same old ledger balance before
either committed its debit.

The pre-fix PostgreSQL reproducer forced two independent provider instances to finish their
10,000 balance reads before either insert. Two concurrent 8,000 requests both returned
`ACCEPTED`, demonstrating a -6,000 effective balance. This was not an idempotency failure: both
requests intentionally used different keys and represented different Operations.

## 2. Idempotency versus concurrency control

The invariants remain separate:

```text
Idempotency:
same Operation/key -> recover the same provider fact, never execute twice

Concurrency control:
different Operations/keys -> serialize the shared source-account funds decision
```

A unique idempotency key cannot constrain the combined amount of different rows. Conversely,
account serialization does not replace provider-ledger uniqueness or stable Operation keys.

## 3. Why the Application check is not authoritative

Transfer Workflow still performs its fresh balance validation before Operation creation. It gives
early feedback and avoids obviously invalid submissions, but the balance can change after that
check and before Provider execution. Tests prepare two 8,000 Operations while both see 10,000,
then let one provider debit commit. The second Operation is rejected by the Provider using the
current 2,000 balance and transitions to `FAILED`.

The final correctness rule therefore lives inside `MockTransferProvider.submit_transfer()`, not in
the Workflow, frontend, LLM, Operation payload, or a cached validation result.

## 4. Provider authoritative balance

The existing model is preserved:

```text
committed synthetic fixture balance
- SUM(mock_bank_transfers.amount WHERE status = 'SUCCEEDED')
= effective available balance
```

No Account persistence redesign or mutable fixture was introduced. The Provider recomputes this
value from its database ledger after acquiring source-account serialization and before inserting
the next provider fact.

## 5. Account serialization primitive and key mapping

PostgreSQL transaction-level advisory locking is used:

```sql
SELECT pg_advisory_xact_lock(:source_account_lock_key)
```

It fits the fixture-backed account model because there is no authoritative database Account row
to lock. It needs no synthetic lock table, expires automatically at transaction end, works across
processes, and keeps the Provider boundary explicit.

`provider_account_lock_key()` hashes the namespaced string
`mock-transfer-provider:source-account:<id>` with SHA-256 and interprets the first eight bytes as a
signed PostgreSQL bigint. It never uses randomized Python `hash()`. A test asserts a hard-coded
mapping in both the pytest process and a separately spawned Python process. Different test account
IDs also produce different keys.

The 64-bit space has a theoretical hash collision risk. For the bounded synthetic account set the
probability is negligible; a collision would conservatively serialize two unrelated accounts,
not permit overspending. It would affect concurrency, not financial correctness.

## 6. Serialization and transaction scope

Only one source account is involved, so one account key is locked and no multi-lock ordering is
needed. Different accounts use different advisory keys and are not globally serialized.

The Provider transaction is short and contains no external network or LLM work:

```text
BEGIN provider transaction
acquire source-account advisory xact lock
re-check existing idempotency fact
recompute effective balance from fixture + ledger
insert SUCCEEDED or FAILED provider fact
COMMIT (automatically releases lock)
```

The Application never holds this financial lock across an Application-to-Provider call. A future
real bank Provider is expected to enforce equivalent atomicity in the bank system itself.

## 7. Idempotency ordering and replay behavior

There is a fast same-key lookup before the provider transaction. Inside the serialized transaction,
the key is checked again before balance calculation. Database uniqueness on
`mock_bank_transfers.idempotency_key` remains the final duplicate-key guard.

This ordering means:

- a completed same-key replay immediately returns the stored provider fact;
- two concurrent same-key calls serialize, and the waiter observes the first fact;
- if the same key races through different source-account inputs, the uniqueness constraint still
  selects one durable fact and the loser reloads it;
- a previously successful 9,000 transfer still replays as success after another transfer reduces
  the current balance to zero; it is never re-evaluated as insufficient funds.

Migration 0010 persists `error_code` and `error_message` on provider facts. This ensures a failed
`INSUFFICIENT_FUNDS` decision also replays with the original definitive reason after a crash,
instead of degrading to a generic rejection.

## 8. Different-key concurrent safety

For the same account, the first transaction to acquire the advisory lock decides and commits.
Only then can the second transaction acquire the lock; its balance query runs under PostgreSQL
`READ COMMITTED` after the first commit and therefore includes the new successful ledger row.

For 10,000 with concurrent 8,000 + 8,000:

```text
one provider fact = SUCCEEDED
one provider fact = FAILED / INSUFFICIENT_FUNDS
successful debit total = 8,000
effective balance = 2,000
```

For 6,000 + 4,000 both succeed and the balance reaches exactly zero. For 8,000 + 3,000, test
assertions are scheduler-independent: exactly one succeeds, one receives insufficient funds, and
the remaining balance equals 10,000 minus the winning amount.

## 9. Different accounts

Account A and Account B map to separate advisory keys. The PostgreSQL test places a synchronization
barrier after each balance read; both requests reach it concurrently and succeed. A global transfer
lock would block the second request before the barrier and fail the test by timeout.

The existing per-instance `asyncio.Lock` remains only as a local contention optimization and is
not the correctness boundary. Tests deliberately use two different Provider instances so those
Python locks cannot coordinate the requests.

## 10. Definitive rejection propagation

Insufficient funds creates a durable Provider row with:

```text
status = FAILED
error_code = INSUFFICIENT_FUNDS
applied_at = NULL
```

It returns a definitive failed submission. Existing `OperationService` transitions the Operation
to `FAILED`, transitions the Workflow to `FAILED`, clears recovery scheduling/lease, and persists
the existing failure events. It is never mapped to `UNKNOWN`.

Network ambiguity and unavailable status queries retain the existing semantics:

```text
Timeout != FAILED
UNKNOWN -> query original Operation status
```

## 11. Recovery compatibility

Foreground submit, manual reconcile, and background recovery all enter the same
`transfer.commit` handler and the same `MockTransferProvider.submit_transfer()` transaction.
There is no bypass around account serialization.

The recovery/concurrency integration test models:

```text
Operation A provider debit succeeds
Application A remains CREATED (crash boundary)
Operation B had already passed stale early validation
Provider rejects B against A's durable debit
background worker recovers A with the original key
```

The result is A `SUCCEEDED`, B `FAILED / INSUFFICIENT_FUNDS`, one successful provider debit, and
2,000 remaining. Recovery of A returns its original provider reference and adds no debit.

## 12. v0.5.1 preflight audits

### Foreground commit versus immediately-due recovery

There is no simultaneous-provider-submit correctness race. After `prepare_transfer()` commits the
immediately due `CREATED` row, both foreground `reconcile()` and the recovery worker must acquire
the same persisted Operation lease. The claim row lock and active-lease exclusion choose one
owner. If recovery wins, foreground may receive `OPERATION_RECONCILIATION_IN_PROGRESS`, but it
cannot submit concurrently. No change was necessary.

### Batch claim lease ageing

The worker does not claim a batch and process it sequentially. It commits the short batch claim,
then immediately dispatches every claim through `asyncio.gather`. Each task validates that its
lease is still active before provider I/O, and the `CREATED -> SUBMITTED` boundary renews a retained
lease. The described Op10 sequential-ageing problem is therefore absent. No worker-pool framework
or additional mechanism was added.

## 13. Migration

Migration `0010_provider_transfer_errors.py` adds nullable `error_code` and `error_message` to
`mock_bank_transfers`. Existing rows remain valid. The migration is not for locking: transaction
advisory locks require no table. It exists solely so definitive Provider decisions survive
same-key replay and Application crash recovery with their original error taxonomy.

No provider account-state/lock table or balance-reservation schema was introduced.

## 14. PostgreSQL verification

Real PostgreSQL tests use independent Provider instances and independent sessions/transactions.
Coverage includes:

- the pre-fix 10,000 / concurrent 8,000 + 8,000 race, now one success and one rejection;
- 6,000 + 4,000 both succeeding to exactly zero;
- 8,000 + 3,000 scheduler-independent nonnegative invariant;
- different accounts reaching synchronized balance reads concurrently;
- ten concurrent same-key submissions producing one row/reference/debit;
- successful replay after current balance later reaches zero;
- insufficient-funds fact/reason replay;
- stable advisory key across separate Python processes;
- stale Application pre-check rejected by Provider;
- provider success + Application crash + background recovery;
- all v0.5.1 SKIP LOCKED, lease/fencing, UNKNOWN query-only, and terminal cleanup regressions.

The Docker product smoke also rebuilt and started PostgreSQL, API, and Web, applied migration 0010,
and drove two fully authorized 12,000 Transfers through the running HTTP API. Both Operations were
committed concurrently against 21,864.52 available funds. One finished `SUCCEEDED`; the other
finished `FAILED / INSUFFICIENT_FUNDS`; the resulting effective balance was 9,864.52.

## 15. Observability

Mock Provider logs bounded events for serialization wait/acquisition, accepted transfer,
insufficient-funds rejection, other definitive rejection, and idempotent replay. Advisory lock keys
are logged for correlation. No idempotency key, transfer payload, credential, reauthentication
secret, API key, or account number is logged.

## 16. Scope exclusions and remaining limitations

No balance reservation, hold/capture/release workflow, account persistence redesign, multi-account
transaction, generic distributed-lock service, or generic concurrency framework was implemented.
The requirement is final commit-time non-overspending, which one explicit Provider transaction
solves.

Transactional Outbox is still absent. A business/event database commit can still be followed by a
process crash before process-local publication; resource APIs remain authoritative. Implementing
Outbox is intentionally deferred rather than partially mixing another reliability mechanism into
this version.

No Redis, Celery, Kafka, generic durable task worker, generic scheduler, microservice split, real
transfer provider, real reauthentication provider, FX, scheduled/recurring transfer,
refund/reversal, Planner, RAG, MCP, Memory, or new Agent was added.

Remaining production limitations include the mock shared PostgreSQL deployment, the theoretical
64-bit advisory-key collision described above, no distributed metrics/tracing, no Outbox, no
reservation semantics, no real provider authentication/contracts, and API-process-hosted Operation
recovery rather than an independently deployed worker service.
