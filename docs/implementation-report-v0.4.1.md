# Implementation Report v0.4.1

Status: `IMPLEMENTED`

## Outcome

04.1 introduces a persistent, deterministic `TRANSFER` workflow that starts from a natural-language message and stops at `READY_FOR_REVIEW`. No transfer execution, approval, reauthentication, OTP, operation, balance mutation, reservation, or transaction write capability exists.

`READY_FOR_REVIEW` means only that the current draft passed preliminary validation. It is not approval, and it does not guarantee that funds will still be available later. A future commit phase must revalidate Policy, Balance, Payee, and Payload.

## State machine

```text
DRAFT
  ├─ missing recipient/amount or ambiguous payee/account → WAITING_FOR_INPUT
  ├─ deterministic rule failure                    → FAILED
  └─ resolved draft → validation pass          → READY_FOR_REVIEW

WAITING_FOR_INPUT
  ├─ versioned Action API → next required input
  ├─ versioned Action API → validation → READY_FOR_REVIEW / FAILED
  └─ cancel                 → CANCELLED

READY_FOR_REVIEW ─ cancel → CANCELLED
```

`VALIDATING` is an allowed domain status, but validation is synchronous and persisted atomically into the next stable state. Tasks complete once the workflow reaches a stable interaction state; the workflow remains the long-lived resource.

## Persistence model

Migration `0006_transfer_workflows.py` adds `workflows` with user, conversation, source task, type, status, version, exact JSON state, and timestamps. Every action uses an atomic `WHERE id + user_id + version` update. A stale `expected_version` returns HTTP 409. Ownership misses return 404.

`state_json` contains `TransferDraft`, `TransferRequiredInput`, `TransferValidationResult`, and `TransferReviewPayload`. Decimal values serialize as strings. Events contain only workflow ID/type/status/version and optional required-input type; full state is never placed in events.

## Router and extraction

`RouteDecision` adds `TRANSFER_WORKFLOW / WORKFLOW`. A transfer mixed with analysis/report/another intent fails closed as `UNSUPPORTED`; no partial task is executed.

`TransferIntentExtractor` makes one strict structured extraction with at most one format-repair attempt. Its schema exposes only:

- `recipient_query`
- `amount`
- `currency`
- `source_account_hint`

Internal IDs are forbidden by Pydantic `extra="forbid"`. Amount input must be an exact decimal string. A second invalid response fails the Task with `TRANSFER_INTENT_EXTRACTION_FAILED`; no values are guessed.

## Payee resolution and ambiguity trace

`payee.search` performs bounded exact normalized matching on display name and phone alias. It returns at most ten masked summaries.

For `给张三转2000`:

```text
Extractor → recipient_query=张三, amount=2000
payee.search → payee_001 (星河银行, ****2231)
             → payee_002 (蓝海银行, ****9102)
Workflow → WAITING_FOR_INPUT / PAYEE_SELECTION
```

No first-item, tail-number, fuzzy-model, or LLM-based choice is made. One match is auto-resolved; zero matches produce `PAYEE_NOT_FOUND`.

## Source account and validation

The workflow calls `account.list` directly as `workflow:transfer`. Only active `DEBIT` and `SAVINGS` accounts are eligible. A unique exact normalized display-name/masked-number hint auto-resolves; absent or ambiguous hints produce `SOURCE_ACCOUNT_SELECTION`. Options include backend balance snapshots for display. Selecting a known credit account deterministically produces `SOURCE_ACCOUNT_NOT_ELIGIBLE`.

Validation uses `Decimal` and covers positive amount, at most two fractional digits, source eligibility, no FX, currency equality, and `available_balance >= amount`. Failures persist stable issue codes. Successful validation builds a deterministic masked review payload.

## Tool and policy boundary

The workflow uses the existing boundary:

```text
TransferWorkflow → ToolRegistry → PolicyService → ToolExecutor → MockBankService
```

Allowed capabilities are exactly `payee.search`, `account.list`, and `account.get_balance`. All are `R1_PRIVATE_READ` and `side_effect=false`. Minimal and Financial Agent capability allowlists were not expanded; `payee.search` is not exposed to either Agent. Registry regression tests prove no transfer commit/submit/send/write capability exists.

## APIs and UI

Workflow creation is message-pipeline-only. Read APIs are user scoped. Versioned action APIs support payee selection, source-account selection, amount setting, and cancellation. There is deliberately no `POST /workflows` creation endpoint.

`TransferWorkflowCard` resolves the resource from `Task.output.workflow_id`, not assistant prose. It renders disambiguated payees, eligible accounts with backend balances, amount input, deterministic review details, and cancel. It never renders a confirm-transfer button. `workflow.*` SSE notifications refresh the authoritative Workflow resource only. Full refresh recovers Conversation, Task, and Workflow from resource APIs.

## Verification summary

- Fake E2E follows two `张三` candidates → payee action → source action → `READY_FOR_REVIEW`.
- Security regression treats `execute_transfer` prompt injection as draft text and exposes zero write capabilities.
- PostgreSQL integration validates migration 0006, JSON round trip, version 2→3→4, stale conflict, ownership, workflow events, and Task reference.
- Real DeepSeek (`deepseek-v4-flash`) smoke reached `READY_FOR_REVIEW` with two candidates and `write_calls=0`.
- Browser E2E completed the UI flow and recovered the same version-4 review state after reload.
- Mock balances and the transaction fixture were byte-for-value unchanged before/after Fake and real-provider workflows.

See `test-results-v0.4.1.md` for commands and counts.

## Known limitations

- 04.1 has no approval, authentication, OTP, operation, execution, idempotency key, FX, balance reservation, or money movement.
- Validation is a snapshot and can become stale.
- `RECIPIENT_QUERY` is represented as a required-input type, but 04.1 intentionally defines no recipient-edit Action endpoint. A request with no recipient must be resubmitted as a new standalone transfer request.
- Event delivery is in-process after database commit; a durable outbox remains future work.
- The development principal is still fixed by the existing local authentication stub.

## Deviations and architecture questions

- `VALIDATING` is not exposed as a durable interactive state because deterministic validation completes within one action transaction. Persisting a transient state would add an extra externally observable version without recovery value.
- The specification includes `RECIPIENT_QUERY` but no corresponding Action API. This implementation preserves the state type and fails safely without interpreting later chat as a business action. 04.2 should decide whether to add a versioned `set-recipient-query` endpoint.
- Approval and Operation domain placeholders predate 04.1, but no tables, services, routes, or execution behavior were added or enabled.
