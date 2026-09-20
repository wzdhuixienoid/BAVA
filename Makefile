.PHONY: up migrate api web test lint typecheck build api-generate agent-smoke postgres-test

up:
	docker compose up --build

migrate:
	cd apps/api && uv run alembic upgrade head

api:
	cd apps/api && uv run uvicorn banking_api.main:app --reload

web:
	pnpm web:dev

test:
	cd apps/api && uv run pytest

lint:
	cd apps/api && uv run ruff check .
	pnpm web:lint

typecheck:
	pnpm web:typecheck

build:
	pnpm web:build

api-generate:
	pnpm api:generate

agent-smoke:
	uv run --project apps/api python scripts/smoke_agent.py

postgres-test:
	cd apps/api && uv run pytest -m postgres
