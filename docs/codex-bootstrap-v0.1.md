# AI Banking Agent — Codex Bootstrap Specification v0.1

Status: `FROZEN FOR BOOTSTRAP`  
Architecture baseline: `v0.1`  
Bootstrap iteration: `Iteration 0`

This document records the normative Iteration 0 contract used to build the repository. It is intentionally limited to an application skeleton; the next-stage Minimal Agent Runtime is out of scope.

## Goal and required flow

Build a structurally correct, persistent, testable modular monolith that proves:

```text
Browser → Next.js → POST message → FastAPI → persisted Conversation/Message
        → Task → deterministic bootstrap runtime → durable state transition
        → persisted Event → SSE → frontend refresh → updated Task UI
```

No real LLM reasoning is part of this iteration.

## Frozen architecture constraints

1. Workflow first, agent second. No Transfer/Card/Subscription/Wealth/Lifestyle agents.
2. The frontend calls the Banking Application API, never an agent framework.
3. Domain models do not depend on an agent framework.
4. Structured persisted state, not `messages[]`, is the business source of truth.
5. Server state is authoritative for Task, Workflow, Approval, and Operation outcomes.
6. Default deny. No high-risk write capabilities are registered.
7. Use one modular-monolith backend; do not split Mock Bank, policy, or runtime into services.
8. Prefer explicit code and boundaries over factories, generic repositories, or universal context/state objects.

## Technology baseline

- Monorepo with Next.js, React, TypeScript, Tailwind CSS
- Python 3.12+, FastAPI, Pydantic/Pydantic Settings, SQLAlchemy 2.x, asyncpg, Alembic
- PostgreSQL; no Redis
- FastAPI `StreamingResponse` SSE and an in-process live event bus
- uv, pytest/pytest-asyncio, ruff, pnpm, ESLint, TypeScript, openapi-typescript

Forbidden runtime dependencies include LangGraph, LangChain, AutoGen, AgentScope, MCP SDKs, vector databases, embeddings/RAG frameworks, Redis, Kafka, RabbitMQ, Celery, Kubernetes, real bank/auth providers, and all LLM SDKs.

## Persisted domain model

Only the following application tables exist in Iteration 0:

- `conversations`: id, user_id, title, created_at, updated_at
- `messages`: id, conversation_id, role, content, created_at
- `tasks`: id, conversation_id, task_type, status, input_json, output_json, error_json, version, created_at, updated_at
- `events`: id, event_type, conversation_id, task_id, global sequence, data_json, created_at

Message roles are `USER`, `ASSISTANT`, and `SYSTEM_NOTICE`; there is no agent-specific role.

Task statuses are `PENDING`, `RUNNING`, `WAITING_USER`, `WAITING_EXTERNAL`, `COMPLETED`, `FAILED`, `CANCELLED`, and `SKIPPED`. The bootstrap runtime uses only `PENDING`, `RUNNING`, `COMPLETED`, and `FAILED`. Every Task transition increments `version`.

Event sequence is globally stable and increasing. Events are persisted; SSE is never the durable source of truth.

## Schema-only boundaries

Workflow, Approval, and Operation domain schemas freeze future concepts but have no tables, APIs, or execution behavior.

- Workflow: id, type, status, version
- Approval: id, workflow id, payload hash, status, timestamps; statuses `PENDING`, `APPROVED`, `REJECTED`, `EXPIRED`, `CONSUMED`, `INVALIDATED`
- Operation: id, workflow id, idempotency key, status, external reference; statuses `CREATED`, `SUBMITTED`, `UNKNOWN`, `SUCCEEDED`, `FAILED`

Workflow means a deterministic business process with explicit state transitions. High-risk financial operations must eventually execute through workflows, not directly through agents.

## Deterministic bootstrap runtime

On an accepted User Message:

1. Persist the User Message.
2. Create a `BOOTSTRAP_MESSAGE_PROCESSING` Task in `PENDING`.
3. Persist and publish `task.created`.
4. Transition the Task to `RUNNING`; persist and publish `task.started`.
5. Perform deterministic processing only.
6. Persist Assistant Message `Bootstrap runtime received your message.`
7. Transition the Task to `COMPLETED`; persist and publish `task.completed`.
8. Persist and publish the assistant message event.
9. A controlled failure transitions the Task to `FAILED` and emits `task.failed`.

An optional short delay may make UI transitions observable, but is not business logic. The runtime must remain easy to delete and must not become the basis of a future agent architecture.

## Boundaries and safety skeletons

- AgentRegistry, SkillRegistry, WorkflowRegistry, and ToolRegistry use simple typed dictionary registration and start empty.
- Tool metadata reserves capability id, name, risk, side effect, and allowed callers. No high-risk writes are registered.
- Policy decisions include `ALLOW`, `DENY`, approval and re-auth variants. Unknown bootstrap capabilities default to `DENY`.
- ContextEnvelope reserves Task, Conversation, memory, upstream results, and constraints. No retrieval, RAG, prompt building, or token budgeting exists.
- MockBankService exposes only deterministic `list_accounts()` and `get_account_summary()` data. It is not a formal tool and implements no write method.

## Persistence and repository rules

Routes never execute SQL directly. Explicit Conversation, Message, Task, and Event repositories are used; there is no generic repository or unit-of-work framework. PostgreSQL is the production database and Alembic owns the schema.

## HTTP API

- `GET /health` → `{"status":"ok"}`
- `GET/POST /api/v1/conversations`
- `GET /api/v1/conversations/{conversation_id}` including Messages
- `POST /api/v1/conversations/{conversation_id}/messages` → 202 with message_id, task_id, request_id
- `GET /api/v1/tasks?conversation_id=...`
- `GET /api/v1/tasks/{task_id}`
- `GET /api/v1/events?conversation_id=...` as SSE

No transfer, purchase, card write, cancellation, `/agents`, `/skills`, or framework-specific endpoint exists. A `DevPrincipal` dependency supplies `dev-user-001`; routes do not hard-code identity.

## Event protocol and SSE

The envelope contains event_id, event_type, timestamp, conversation_id, nullable task_id, sequence, and data. Supported events are:

- `conversation.message.created`
- `conversation.message.completed`
- `task.created`
- `task.started`
- `task.completed`
- `task.failed`

Names describe domain/runtime state, never internal agents. The in-memory bus is explicitly single-process bootstrap transport. On disconnect, clients recover Conversation and Task resources through GET; replay and distributed fan-out are deferred.

## Frontend contract

The workspace supports creating/loading Conversations, sending Messages, showing user/assistant Messages, and listing Task type/status/id. It connects an `EventSource` for the selected Conversation. Every relevant event causes authoritative Conversation and Task data to be re-fetched. Only selection, composer input, connection state, and view state are local UI facts.

Pydantic/OpenAPI is the source of API types. `pnpm api:generate` reads a running FastAPI `/openapi.json` into `packages/api-client/src/schema.d.ts`.

## Compose and environment

Compose contains only PostgreSQL, API, and web services. `.env.example` declares PostgreSQL, database URL, API host/port, web port, and public API base URL. `docker compose up --build` is the target full-stack command.

## Required validation

- Health 200
- Conversation and Message persistence
- Message creates Task
- Runtime reaches persisted `COMPLETED` and supports persisted `FAILED`
- State transitions produce durable, ordered Events
- Live event transport delivers persisted events
- Backend test suite and ruff pass
- Frontend lint, typecheck, and production build pass
- OpenAPI TypeScript generation succeeds
- Repository dependency audit finds no LLM, agent framework, MCP, RAG/vector, Redis, or high-risk banking execution dependency/capability

## Current limitations

Iteration 0 has no LLM, agent, real skill, concrete workflow, approval execution, operation execution, re-authentication, memory, RAG, scheduler, worker, distributed event transport, real banking API, or real authentication. Bootstrap completion ends this iteration; no next-stage capability may be added without a new specification.

## Architecture questions

None discovered during bootstrap implementation.

