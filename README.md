# AI Banking Agent

Iteration 0 is an application skeleton for a future banking agent. It proves durable application state and a complete browser → API → database → deterministic runtime → SSE → browser loop without using an LLM or an agent framework.

The frozen design is documented in [Architecture Baseline v0.1](docs/architecture-baseline-v0.1.md) and [Codex Bootstrap Specification v0.1](docs/codex-bootstrap-v0.1.md).

## Architecture

```text
Next.js UI ── HTTP/SSE ── FastAPI modular monolith ── PostgreSQL
                              │
                              ├─ ConversationService
                              ├─ TaskService
                              ├─ deterministic BootstrapRuntime
                              └─ durable Events + in-process live transport
```

The frontend displays server-owned Conversation, Message, and Task state. SSE is only a live notification transport; a reconnect or page refresh recovers state from the resource APIs. The bootstrap runtime is deliberately replaceable and is not an agent.

## Prerequisites

- Docker with Docker Compose for the full stack, or PostgreSQL 15+ for local development
- Python 3.12+ and [uv](https://docs.astral.sh/uv/)
- Node.js 22+ and pnpm 11+

## Start the full stack

```bash
cp .env.example .env
docker compose up --build
```

The web app is available at `http://localhost:3000`, the API at `http://localhost:8000`, and OpenAPI at `http://localhost:8000/docs`. The API container runs Alembic migrations before starting.

## Local development

Use a local PostgreSQL URL (host `localhost`, not the Compose service name) in `.env`.

```bash
cd apps/api
uv sync
uv run alembic upgrade head
uv run uvicorn banking_api.main:app --reload
```

In another terminal:

```bash
pnpm install
pnpm web:dev
```

## Database migrations

```bash
cd apps/api
uv run alembic upgrade head
```

Iteration 0 creates exactly four application tables: `conversations`, `messages`, `tasks`, and `events` (plus Alembic's version table).

## Tests and validation

```bash
cd apps/api
uv run ruff check .
uv run pytest

cd ../..
pnpm web:lint
pnpm web:typecheck
pnpm web:build
```

Backend tests use an isolated async SQLite database for fast repository/application/API tests; production and Compose use PostgreSQL through `asyncpg`.

## Generate frontend API types

Start FastAPI on port 8000, then run:

```bash
pnpm api:generate
```

This reads `/openapi.json` and replaces `packages/api-client/src/schema.d.ts`. Pydantic schemas remain the source of truth; the web app imports the generated types.

## Implemented in Iteration 0

- Dev principal injection with fixed user `dev-user-001`
- Durable Conversation, Message, Task, and Event models
- Message submission and deterministic `BOOTSTRAP_MESSAGE_PROCESSING`
- Task transitions `PENDING → RUNNING → COMPLETED` and controlled `FAILED`
- Globally increasing persisted event sequence
- Conversation-filtered SSE with keep-alives
- Conversation/message/task workspace and reconnect-safe server refreshes
- Empty Agent, Skill, Workflow, and Tool registries
- Default-deny PolicyService, ContextBuilder boundary, and read-only MockBankService
- Workflow, Approval, and Operation schemas without tables or execution

## Current limitations

- `BootstrapRuntime` is temporary deterministic test infrastructure, not an agent runtime.
- The live event bus is process-local. PostgreSQL Events are durable; live fan-out is not distributed.
- SSE replay via `Last-Event-ID` is not implemented. Clients recover resources through GET APIs.
- Authentication is a development-only fixed principal.
- There is no background worker; runtime work is attached to the API process.
- Compose validation requires Docker, which must be installed on the development host.

Not implemented: LLM calls, LangGraph/LangChain, MCP, RAG, embeddings, vector databases, Redis, workers, real banking APIs, real authentication, approvals, operations, concrete workflows, agents, or executable skills. There are no transfer, investment purchase, card freeze, or subscription cancellation endpoints/tools.

