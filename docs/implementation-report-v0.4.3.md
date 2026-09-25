# Implementation Report v0.4.3

## Outcome

04.3 completes the first Transfer vertical slice. A validated, approved, and reauthenticated payload can create exactly one durable `TRANSFER` Operation, consume its Approval in the same application-database transaction, submit through the Tool/Policy boundary with a stable idempotency key, and reach a provider-confirmed terminal result.

The LLM participates only in the original route and `TransferIntent` extraction. Approval, reauthentication, operation preparation, provider submission, and reconciliation are deterministic Workflow Actions. No Transfer, Payment, or Operation Agent was added.

## Operation state machine

```text
READY_FOR_COMMIT
  -- commit + final checks --> Operation CREATED + Approval CONSUMED
                              Workflow COMMITTING

CREATED   -- submit same key --> SUBMITTED / UNKNOWN / FAILED
SUBMITTED -- status query ----> SUBMITTED / UNKNOWN / SUCCEEDED / FAILED
UNKNOWN   -- status query ----> UNKNOWN / SUBMITTED / SUCCEEDED / FAILED

Operation SUCCEEDED --> Workflow SUCCEEDED
Operation FAILED    --> Workflow FAILED
```

`UNKNOWN` is a first-class, non-failure state. It means the provider may have accepted or executed the request but the application cannot yet prove the outcome. UNKNOWN reconciliation only calls `transfer.get_status`; it never submits again, creates another Operation, or rotates the idempotency key.

Only `Operation.status == SUCCEEDED` is the product success boundary. An HTTP response, provider reference, `SUBMITTED`, or Workflow `COMMITTING` is never rendered as “转账成功”.

## Atomic approval consumption

`OperationService.prepare_transfer()` opens the application transaction by loading the user-owned Workflow with a row lock. It checks `expected_version`, `READY_FOR_COMMIT`, current canonical payload hash, Approval state/TTL/unconsumed status, Reauthentication state/TTL/binding, final Policy, and fresh deterministic business data.

The following are committed atomically:

```text
Operation(CREATED, immutable payload, stable UUIDv4 idempotency_key)
+ Approval(CONSUMED, consumed_at, consumed_by_operation_id)
+ Workflow(COMMITTING, version + 1)
+ safe audit Events
```

The provider call occurs only after that transaction commits. The schema enforces unique `idempotency_key`, unique `approval_id`, unique `consumed_by_operation_id`, and unique `(workflow_id, operation_type)`. Therefore an Approval cannot be consumed without its Operation, and one Transfer Workflow cannot create a second Transfer Operation.

Authorization TTL is checked only at Operation creation. Once CREATED exists, its immutable payload is the already-consumed authorization boundary; recovery is allowed even if Approval or Reauthentication subsequently expires.

## Final authorization, Policy, and business checks

Commit does not trust `READY_FOR_COMMIT` by itself and accepts no financial fields from the frontend. It rebuilds the authoritative Review Payload and recomputes the canonical SHA-256 hash, then verifies the current Approval and the VERIFIED Reauthentication bound to that Approval.

Before creating an Operation it independently evaluates `transfer.commit` through `PolicyService` and freshly resolves/checks:

- payee existence and current deterministic match;
- source-account existence, ACTIVE state, and DEBIT/SAVINGS eligibility;
- positive `Decimal` amount with at most two decimals;
- source currency equality (no FX);
- current effective available balance.

A final failure moves the Workflow to definitive `FAILED` with stable validation issues, but creates no Operation, consumes no Approval, calls no provider, and moves no funds. Approval expiry repairs the Workflow to `READY_FOR_REVIEW`; Reauthentication expiry repairs it to `REAUTH_REQUIRED`.

## Tool and Policy boundary

The only financial write capability is:

```text
transfer.commit
risk_level = R4_FINANCIAL_COMMIT
side_effect = true
allowed_callers = ["workflow:transfer"]
```

`transfer.get_status` is `R1_PRIVATE_READ`, `side_effect=false`, and has the same sole caller. Commit Tool input contains only `operation_id`; the handler reloads the authoritative Operation payload and idempotency key. The execution path is:

```text
Workflow Action
→ OperationService
→ TransferWorkflowEngine
→ ToolRegistry
→ PolicyService
→ ToolExecutor
→ transfer.commit / transfer.get_status handler
→ TransferProvider
```

Minimal Banking Agent, Financial Analysis Agent, and Monthly Report Skill permissions remain unchanged. Regression tests force all three caller identities against `commit_transfer` and receive `TOOL_NOT_ALLOWED` before the handler runs.

## Provider boundary and persistent ledger

`TransferProvider` defines `submit_transfer()` and `get_transfer_status()`. Production orchestration depends only on this protocol. `MockTransferProvider` stores external-bank simulation facts in `mock_bank_transfers`, separate from application `operations`:

```text
operations            = what the product believes it is executing
mock_bank_transfers   = what the simulated bank accepted/applied
```

The provider ledger has a database-unique idempotency key. Replaying a key returns the existing provider reference/result. Effective balance is calculated as committed synthetic base balance minus successful outgoing provider-ledger rows, so `accounts.json` and `transactions.json` remain immutable fixtures.

Fault modes are deterministic:

- `SUCCESS`: applies one debit, submission is accepted, status query confirms SUCCEEDED.
- `DEFINITIVE_FAILURE`: persists an explicit failed provider result and applies zero debit.
- `TIMEOUT_AFTER_ACCEPT`: applies/persists once, loses the response, maps locally to UNKNOWN, then status query confirms SUCCEEDED.

## Crash and idempotency traces

Crash Test A commits `Operation CREATED + Approval CONSUMED + Workflow COMMITTING`, reconstructs services before any provider call, and reconciles the same Operation/key to SUCCEEDED with one debit.

Crash Test B lets the provider apply the transfer while local Operation remains CREATED, reconstructs application flow, and resubmits the same key. The provider returns the existing result and the total debit remains one.

The direct provider replay test submits one key ten times and observes one provider row, one provider reference, and one effective debit. The double-commit test observes one successful action, one stale HTTP 409, and one Operation.

## APIs, ownership, and optimistic concurrency

Added:

```text
POST /api/v1/workflows/{workflow_id}/actions/commit
GET  /api/v1/operations/{operation_id}
POST /api/v1/operations/{operation_id}/actions/reconcile
```

There is no arbitrary Operation create endpoint. Commit accepts only `expected_version`; reconcile also requires `expected_version`. User ownership is included in every resource lookup and another user receives 404. The frontend-safe Operation resource and Workflow summary exclude `idempotency_key` and the execution payload.

Cancel is allowed only before an Operation exists. CREATED, SUBMITTED, UNKNOWN, SUCCEEDED, and FAILED Operations cannot be cancelled or reused.

## Events and safe logging surface

Added `operation.created`, `operation.submitted`, `operation.unknown`, `operation.succeeded`, `operation.failed`, `workflow.committing`, and `workflow.succeeded`. Event metadata is bounded to IDs, type, status, version, provider reference, and safe error code. It excludes idempotency keys, payloads, account numbers, reauthentication values, prompts, and reasoning.

## UI and recovery

`READY_FOR_COMMIT` now shows a distinct red “提交转账” execution action and explicitly warns that it moves funds. COMMITTING disables resubmission. UNKNOWN shows “转账状态确认中 / 银行可能已经收到这笔请求，请勿重复提交” and a “检查状态” action. FAILED is definitive and never auto-retries. SUCCEEDED renders amount, currency, payee, source account, provider reference, and completion time from authoritative state.

SSE `operation.*` and new `workflow.*` events trigger resource refresh only. Browser refresh reconstructs Workflow/Operation from PostgreSQL.

## Verification evidence

- Fake/backend E2E: normal success, definitive failure, timeout-after-accept, final-balance change, Policy deny, stale action, ownership, expiry repair, security caller denial, and exact-once provider replay pass.
- PostgreSQL: migration 0008, Operation/ledger persistence, Approval consumption linkage, CREATED restart recovery, effective balance, stable key, and ownership isolation pass.
- Real DeepSeek: only route/intent use the model; deterministic actions finish `Workflow SUCCEEDED`, `Operation SUCCEEDED`, `Approval CONSUMED`, balance delta `-2000.00`, provider count 1.
- Browser: two 张三 → 工资卡 → Approval → Reauthentication → Submit → “转账成功”; salary balance changed from 23,864.52 to 21,864.52 and remained recovered after refresh.
- UNKNOWN integration: TIMEOUT_AFTER_ACCEPT first produces UNKNOWN/COMMITTING, then query-only reconciliation reaches SUCCEEDED with one debit.

## Security regression

Prompt text cannot approve, reauthenticate, create an Operation, or invoke `transfer.commit`. Even an injected request to skip all states is limited by deterministic actions, ownership, `expected_version`, payload hash binding, Tool Policy, unique Operation constraints, and provider-side idempotency.

## Known limitations

- The provider and step-up provider are development mocks, not bank/SMS integrations.
- There is no scheduled/background reconciler; a CREATED/SUBMITTED/UNKNOWN Operation is advanced by the commit response path or explicit reconcile action.
- The event bus is process-local and there is no Outbox. PostgreSQL resources remain authoritative after restart.
- Per-account provider serialization is process-local. Database uniqueness guarantees same-key exact-once behavior; multi-process balance serialization is intentionally deferred with the rest of multi-worker architecture.
- There is no balance reservation, FX, scheduled/recurring transfer, post-submit cancellation, reversal, or refund.

## Deviations and architecture questions

The mock provider ledger is stored in the same PostgreSQL deployment but in a separate table and protocol boundary. This keeps the teaching distinction between product Operation facts and provider facts without introducing another service or database.

No generic Saga engine, payment platform, authorization DSL, Outbox, queue, or worker framework was introduced. The next architecture review should decide whether production provider integration requires an Outbox/worker lease, cross-process per-account serialization, and automated reconciliation cadence. Per the 04.3 scope, implementation stops here.
