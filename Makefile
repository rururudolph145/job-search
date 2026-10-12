.PHONY: sync db-up db-down migrate dev lint typecheck test

sync:
	uv sync --all-packages

db-up:
	docker compose up -d

db-down:
	docker compose down

migrate:
	uv run --package jobsearch-backend alembic -c backend/alembic.ini upgrade head

dev:
	uv run --package jobsearch-backend uvicorn app.main:app --reload

lint:
	uv run ruff check . && uv run ruff format --check .

typecheck:
	uv run mypy backend/app shared/jobsearch_shared

test:
	uv run pytest
