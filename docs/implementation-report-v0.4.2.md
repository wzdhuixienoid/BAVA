# Implementation Report v0.4.2

## Outcome

04.2 extends the persistent transfer workflow from `READY_FOR_REVIEW` through explicit payload approval and step-up reauthentication to `READY_FOR_COMMIT`. It deliberately adds no money-movement capability: there is no transfer write tool, balance mutation, transaction write, operation table, or submit button.

`READY_FOR_COMMIT` means only that the current validated draft is covered by an unexpired Approval and a verified Reauthentication bound to that Approval. It does not mean that money was transferred. A future 04.3 commit must recheck the payload hash, Approval, Reauthentication, policy, payee, source account, balance, and currency.

## State machine

```text
READY_FOR_REVIEW
  -- approve(current payload, expected_version) --> REAUTH_REQUIRED
  -- draft mutation -----------------------------> revalidation

REAUTH_REQUIRED
  -- start-reauth -------------------------------> REAUTH_REQUIRED + PENDING challenge
  -- verify(valid code) --------------------------> READY_FOR_COMMIT
  -- draft mutation ------------------------------> invalidate auth + revalidation

READY_FOR_COMMIT
  -- draft mutation ------------------------------> invalidate auth + revalidation
  -- cancel --------------------------------------> CANCELLED
```

All actions reload the authoritative, user-owned workflow and require `expected_version`. A stale action returns HTTP 409 and is never silently retried.

## Approval domain

`Approval` is a PostgreSQL first-class resource with `TRANSFER` type and the statuses `PENDING`, `APPROVED`, `INVALIDATED`, and `EXPIRED`. The stored payload contains only business identity fields:

```json
{"amount":"2000.00","currency":"CNY","payee_id":"payee_001","source_account_id":"acc_salary"}
```

`canonicalize_transfer_payload()` normalizes currency to uppercase, amount to an exact two-decimal string, and field names to the fixed schema above. `canonical_transfer_json()` uses UTF-8-compatible JSON, sorted keys, and compact separators. `payload_hash` is the lowercase hex SHA-256 digest of those canonical JSON bytes. Presentation text, masked formatting, and display names are excluded.

The approve action first reruns deterministic payee/account/balance/currency validation and rebuilds the authoritative Review Payload. Only that fresh payload is canonicalized and hashed; the backend does not approve a stale UI snapshot.

Approval defaults to a 600-second server-enforced TTL. `consumed_at` is persisted but remains null in 04.2; single-use consumption belongs to 04.3.

## Reauthentication domain

`Reauthentication` is an independent PostgreSQL resource with `PENDING`, `VERIFIED`, `FAILED`, `EXPIRED`, and `INVALIDATED` states. Every challenge is bound to one `approval_id`, `workflow_id`, and `user_id`; it cannot authorize another Approval or workflow.

`ReauthenticationProvider` is the replacement boundary for a future bank/SMS provider. The local `MockReauthenticationProvider` compares the submitted value with a server-side development secret. The default challenge TTL is 300 seconds and the default maximum is three attempts. Failed attempts increment durable `attempt_count`; reaching the limit marks only that challenge `FAILED`, after which a new challenge may be started.

The verification value is passed directly to the provider. It is not placed in workflow state, Approval payloads, events, GET responses, or application logging.

## Persistence and safe resource recovery

Migration `0007_transfer_approval_reauth.py` adds `approvals` and `reauthentications` plus the two workflow enum values. It does not add an operations table. Workflow GET/list responses include only safe `approval_summary` and `reauth_summary` metadata. Browser refresh reconstructs `READY_FOR_COMMIT` from PostgreSQL; SSE events only trigger refresh and are not authoritative state.

Workflow authorization state contains identifiers and safe timestamps only:

```text
approval_id, approval_payload_hash, approval_expires_at
reauth_id, reauth_verified_at, reauth_expires_at
```

## Actions and invalidation

Implemented deterministic Workflow Actions:

- `set-recipient-query`
- `select-payee`
- `select-source-account`
- `set-amount`
- `approve`
- `start-reauth`
- `verify-reauth`
- `cancel`

Approval cannot be created by a chat message, and Reauthentication cannot be completed in chat. Any payee, recipient query, source-account, amount, or resulting currency change invalidates active Approval and Reauthentication records, clears the authorization snapshot, and reruns deterministic resolution and validation. Cancel performs the same invalidation before entering `CANCELLED`.

## Tool and policy boundary

`workflow:transfer` still has exactly three read-only capabilities:

```text
payee.search
account.list
account.get_balance
```

They remain `R1_PRIVATE_READ`, `side_effect=false`, and execute through Registry → Policy → Executor → MockBankService. Approval and Reauthentication are Workflow Actions, not LLM tools. Minimal Banking Agent, Financial Analysis Agent, and Monthly Report Skill permissions are unchanged. No Transfer, Approval, or Auth Agent was introduced.

## Events

Added Approval/Reauthentication and workflow transition events, including `approval.created`, `approval.approved`, `approval.invalidated`, `approval.expired`, `reauth.challenge.created`, `reauth.verified`, `reauth.failed`, `reauth.expired`, `reauth.invalidated`, `workflow.reauth_required`, and `workflow.ready_for_commit`.

Payloads contain only workflow/resource identifiers, status, version, and safe expiry timestamps. They exclude canonical payload contents, verification values, full account numbers, prompts, and reasoning traces.

## UI

The Transfer card now:

- uses “确认这笔转账” for Approval, never “立即转账”;
- starts and verifies a step-up challenge outside chat;
- shows “尚未提交转账” at `READY_FOR_COMMIT` with no submit button;
- exposes deterministic draft editing in review/reauth/ready states and warns that edits invalidate authorization;
- restores workflow, Approval summary, and Reauthentication summary after refresh;
- refreshes authoritative workflow state on `workflow.*`, `approval.*`, and `reauth.*` SSE events.

## Verification traces

Fake E2E covers two 张三 candidates, account selection, Approval, challenge creation, verification, `READY_FOR_COMMIT`, payload mutation invalidation, safe event payloads, and unchanged bank data.

The real DeepSeek smoke uses the model only for route and semantic intent extraction. Payee/account selection, Approval, and Reauthentication use deterministic services. It reached `READY_FOR_COMMIT` with `APPROVED` + `VERIFIED` and reported zero writes, unchanged balances, and unchanged transactions.

Browser E2E completed the full UI flow, displayed two disambiguated 张三 choices, selected 工资卡, approved the exact review, performed local step-up authentication, displayed “尚未提交转账”, refreshed, and recovered `READY_FOR_COMMIT` version 7.

Security regression tests prove that chat confirmation and prompt requests to bypass authentication cannot create Approval, complete Reauthentication, or invoke a transfer write. Automated mutation tests prove that changing 2000 to 20000 invalidates both prior authorization records and produces a different payload hash.

## Zero-money-movement proof

- Registered transfer write capabilities: **0**.
- Balance mutation methods called or added: **0**.
- Transaction writes called or added: **0**.
- Operation tables added: **0**.
- Approval `consumed_at` values in 04.2: **null**.
- Fake E2E, PostgreSQL integration, DeepSeek smoke, and browser recovery all observed unchanged synthetic balances and transaction fixtures.

## Known limitations

- The provider is a local/test mock; production step-up delivery and verification are not implemented.
- Expiry is enforced when an authorization-dependent action is attempted; GET may display an expiry timestamp that has just passed until the next authoritative action refreshes state.
- 04.2 has no approval consumption, operation ledger, idempotency key, transfer submission, retry, reservation, or balance freeze.
- The current app event bus remains process-local; PostgreSQL resources are authoritative across refresh/restart.

## Deviations and architecture questions

The suggested separate ApprovalService/ReauthenticationService files were not introduced. Their transaction-sensitive orchestration remains narrowly inside `WorkflowService`, while provider, domain, repository, and canonicalization boundaries are separate. This avoids a generic authorization framework and keeps optimistic workflow updates and authorization records in one database transaction.

For 04.3, the open design question is the atomic boundary between Approval consumption, operation creation, final bank-side idempotency, and the mandatory fresh policy/business validation. None of that boundary is prematurely implemented here.
