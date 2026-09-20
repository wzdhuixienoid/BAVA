# AI Banking Agent — Test Results v0.1

Validation timestamp: `2026-09-20 14:57 CST`  
Environment: macOS arm64, Docker Engine `29.8.0`, Docker Compose `5.5.1`  
Overall result: `PASS`

## Backend static analysis

Command:

```bash
apps/api/.venv/bin/ruff check apps/api
```

Result:

```text
All checks passed!
```

## Backend tests

Command:

```bash
apps/api/.venv/bin/pytest -q apps/api/tests
```

Result:

```text
.......                                                                  [100%]
7 passed in 0.14s
```

Coverage by behavior:

| Area | Validation | Result |
| --- | --- | --- |
| Health | `GET /health` returns 200 | PASS |
| Conversation | Create and reload persisted Conversation | PASS |
| Message → Task | User Message persisted and bootstrap Task created | PASS |
| Completion | Task reaches `COMPLETED`, version 3 | PASS |
| Failure | Controlled error reaches `FAILED` and persists error | PASS |
| Events | Required events persisted in stable sequence | PASS |
| Live transport | EventBus subscriber receives persisted events | PASS |

## Frontend lint

Command:

```bash
pnpm web:lint
```

Result: `PASS` — ESLint completed with no errors or warnings.

## Frontend typecheck

Command:

```bash
pnpm web:typecheck
```

Result: `PASS` — `tsc --noEmit` completed successfully.

## Frontend production build

Command:

```bash
pnpm web:build
```

Result:

```text
✓ Compiled successfully
✓ Generating static pages (4/4)

Route (app)       Size       First Load JS
/                 3.27 kB    105 kB
/_not-found       986 B      103 kB
```

## OpenAPI TypeScript generation

Command:

```bash
pnpm api:generate
```

Result:

```text
http://localhost:8000/openapi.json → packages/api-client/src/schema.d.ts
540 lines generated
```

Result: `PASS`.

## Docker Compose build and startup

Command:

```bash
docker compose up --build -d
docker compose ps
```

Result: `PASS`.

| Service | Runtime result |
| --- | --- |
| `postgres` | Running, healthcheck `healthy`, PostgreSQL 17 |
| `api` | Running on `0.0.0.0:8000`; Alembic migration successful |
| `web` | Running on `0.0.0.0:3000`; Next.js production server ready |

HTTP checks:

```text
GET http://localhost:8000/health → 200 {"status":"ok"}
GET http://localhost:3000/       → 200 OK
```

## PostgreSQL persistence validation

Current acceptance-data snapshot after API and browser validation:

```text
conversations=2
messages=6
tasks=3
events=15
```

The counts are development acceptance data, not seed fixtures. Earlier Task resources remained readable after the API container was rebuilt, demonstrating that state resides in PostgreSQL rather than process memory.

## End-to-end HTTP/SSE validation

Validated flow:

```text
POST Conversation
→ connect SSE
→ POST Message "Hello"
→ 202 with message_id/task_id/request_id
→ conversation.message.created sequence=1
→ task.created status=PENDING version=1 sequence=2
→ task.started status=RUNNING version=2 sequence=3
→ task.completed status=COMPLETED version=3 sequence=4
→ conversation.message.completed sequence=5
→ GET Conversation returns USER + ASSISTANT messages
→ GET Task returns COMPLETED version=3
```

Result: `PASS`.

## Browser validation

The real Next.js UI was opened at `http://localhost:3000` and verified to show:

- restored Conversation and Messages;
- `SSE connected` indicator;
- Task ID/type/status from the server;
- a new User Message sent through the Message Composer;
- deterministic Assistant reply;
- a second Task updated to `COMPLETED` in real time.

Browser console error count: `0`.

Result: `PASS`.

## Dependency and safety validation

Manifests contain no runtime dependency on LLM SDKs, LangGraph/LangChain, MCP, RAG/vector databases, Redis, Kafka, RabbitMQ or Celery. No executable transfer, investment purchase, card freeze or subscription cancellation endpoint/tool is implemented.

Result: `PASS`.

## Final assessment

All executable Iteration 0 validation categories passed. The known limitations in the Implementation Report are intentional Bootstrap scope boundaries, not failed acceptance criteria.

