.PHONY: up migrate api web test lint typecheck build api-generate agent-smoke postgres-test docs package

up:
	docker compose up --build

migrate:
	cd apps/api && uv run --env-file ../../.env alembic upgrade head

api:
	cd apps/api && uv run --env-file ../../.env uvicorn banking_api.main:app --reload

web:
	pnpm web:dev

test:
	uv run --project apps/api pytest apps/api/tests -m 'not postgres and not sandbox'
	pnpm --filter @banking/web test

lint:
	uv run --project apps/api ruff check apps/api scripts
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

docs:
	python3 scripts/check_docs.py

package: docs
	python3 scripts/package_source.py
