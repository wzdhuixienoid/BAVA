FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim AS runtime

WORKDIR /app
COPY pyproject.toml uv.lock* ./
RUN uv sync --frozen --no-dev
COPY alembic.ini ./
COPY migrations ./migrations
COPY src ./src

EXPOSE 8000
CMD ["sh", "-c", "uv run alembic upgrade head && uv run uvicorn banking_api.main:app --host 0.0.0.0 --port 8000"]

