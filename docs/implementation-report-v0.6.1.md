# Implementation Report v0.6.1

## 1. Previous security gap

v0.5.4 resolved every request to one development user. That was useful for fixtures but was not an authentication boundary: an external identity was not cryptographically verified, durable work did not carry an explicit Task owner, and browser/API/tool authority was not derived from a request Principal.

v0.6.1 replaces that implicit model with:

```text
OIDC Identity Provider
→ verified JWT credential
→ Principal
→ internal user_id
→ resource ownership + Policy
→ Agent / Skill / Workflow / Tool
```

## 2. OIDC credential verification

`AuthenticationService` is the single FastAPI authentication boundary. In `AUTH_MODE=oidc` it accepts a Bearer JWT and verifies it with PyJWT and an asymmetric JWKS key. Verification covers signature, configured issuer and audience, expiration, optional not-before, non-empty subject, configured algorithm allowlist, and `kid` key selection. `none` and symmetric HMAC algorithms are rejected by Settings validation.

Keys are loaded only from the configured `OIDC_JWKS_URL`, or from the configured issuer's standard discovery document. Token-provided key URLs are never used. JWKS is cached and an unknown `kid` triggers one forced refresh to support normal signing-key rotation. Tests use local RSA keys and an in-process JWKS HTTP transport; they do not contact an external identity provider.

Missing, invalid, expired, wrong-issuer, wrong-audience, not-yet-valid, bad-signature and disallowed-algorithm credentials return 401 without logging or returning the raw token.

## 3. Principal construction

The authenticated request receives an immutable `Principal` containing the stable application `user_id`, external `issuer` and `subject`, plus optional `auth_time`, `amr` and `acr`. Routes receive it only through `get_current_principal()` and use `Principal.user_id` for application authorization.

The OIDC `sub` value is not copied into business domain models. Background execution uses a separate immutable `ExecutionPrincipal`, created server-side from authoritative Task, Workflow or Operation ownership.

## 4. External identity mapping

Migration `0013` adds the minimal `identity_mappings` table:

- stable internal `user_id`;
- external `issuer` and `subject`;
- `created_at`;
- database `UNIQUE(issuer, subject)`.

An authenticated identity without a mapping receives `403 IDENTITY_NOT_PROVISIONED`. It is never mapped to the development user, an existing account, email or display name. Provisioning is explicit through `python -m banking_api.security.authentication.provision` or controlled seed data. The same `subject` under another issuer is a distinct namespace.

## 5. Resource ownership

Conversation, Message-by-Conversation, Task, Event, Report, Workflow, Approval, Reauthentication and Operation access is scoped to the current internal user. Detail and action endpoints query by both resource ID and `user_id`, returning 404 for absent and foreign resources. List endpoints apply the user predicate in SQL rather than loading all users and filtering in Python.

Workflow approval, reauthentication, commit/cancel and Operation reconcile endpoints re-read the authenticated Principal on every request. Request bodies cannot select the owner. Existing Approval payload hashes, Reauthentication state and Transfer safety rules are unchanged.

## 6. Account, payee and financial tool scope

`ToolExecutionContext` now contains a trusted Principal. `ToolExecutor` derives authentication from its presence; callers cannot pass an `authenticated=True` flag. Account listing, balance, payee search, deterministic transaction analytics and transfer provider ledger access all use `context.principal.user_id`.

Tool input schemas do not expose `user_id`, `principal_id` or `subject` and reject extra authority fields. A model-generated attempt to request another user therefore cannot change the server-created context. Mock bank fixtures are explicitly assigned to configured fixture users, so an unknown or differently mapped identity inherits no banking data.

## 7. Durable Task identity

Migration `0013` adds non-null `tasks.user_id`, backfilled from the owning Conversation. Message acceptance persists that owner atomically with the Task. A worker claim contains the Task owner; before execution the runner verifies claim, Task and Conversation owners agree, then creates `ExecutionPrincipal.for_task(task.user_id)`.

No access token, refresh token, ID token or Authorization header is stored in Task input/output/error, Message, Event, Outbox, checkpoint or prompt. Token expiry after the HTTP request therefore does not change the ownership of already accepted durable work.

Recovery creates execution authority only from the claimed Operation's stored `user_id`; prompt text and model output are not authority sources.

## 8. SSE authentication

The SSE route uses the same Principal dependency and verifies Conversation ownership before subscribing. Foreign UUIDs return 404. The web client replaced browser `EventSource` with authenticated streaming `fetch`, carrying the Bearer credential in a header rather than in a query string. Resource APIs remain the source of truth.

## 9. Frontend authentication

The Next.js client uses `oidc-client-ts` with Authorization Code + PKCE. It provides login, auth state, logout, unauthenticated gating and Bearer headers for API/SSE calls. Access tokens are held in the OIDC client's in-memory user store; protocol state uses `sessionStorage`, but access, refresh and ID tokens are not persisted there or in `localStorage`.

No password UI, credential database or authorization server was added. OIDC authority, client ID and scopes are deployment configuration.

## 10. Authentication, Approval and Reauthentication

The boundaries remain independent:

- Authentication establishes the current Principal.
- Resource ownership and existing Policy determine what that Principal may access.
- Approval binds consent to the canonical transfer payload.
- Reauthentication records a separate high-risk verification step.

OIDC login does not consume, bypass or replace Approval/Reauthentication. `MockReauthenticationProvider` remains for v0.6.1; a real step-up provider is deferred to v0.6.2.

## 11. Development isolation

`AUTH_MODE` is required. Development mode returns only the configured fixed `DEVELOPMENT_USER_ID`; no request header can choose another user. Missing OIDC configuration does not fall back to development. `APP_ENVIRONMENT=production` together with `AUTH_MODE=development` fails Settings validation during startup.

## 12. Isolation and regression coverage

New tests cover local JWT/JWKS verification and rotation, identity provisioning namespaces, production fail-closed configuration, cross-user Conversation/Task/Event/SSE/Report/Workflow/Operation isolation, protected actions, banking data/tool isolation, prompt-injected authority arguments, and durable Task execution without persisted credentials.

The existing Operation recovery, provider concurrency, Outbox and Task lease/heartbeat protocols were not redesigned. Their regression suites remain the evidence that the authentication changes did not alter those boundaries. Exact executed commands and results are recorded in [Test Results v0.6.1](test-results-v0.6.1.md).

## 13. Current limit and v0.6.2

This release implements a provider-neutral, production-capable OIDC/JWT protocol boundary, but no real external IdP credentials were available for an end-to-end login smoke. Real external OIDC login is therefore recorded as not executed, not as deployed.

v0.6.2 should integrate a real step-up Reauthentication provider. It should not conflate that work with normal login, Approval, or the unchanged Transfer/Operation safety boundary.
