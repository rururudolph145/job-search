# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Install all workspace dependencies (run after cloning or adding packages)
make sync          # uv sync --all-packages

# Start Postgres + pgvector (Docker Compose)
make db-up         # docker compose up -d
make db-down       # docker compose down

# Run Alembic migrations against the local DB
make migrate       # alembic upgrade head

# Run the FastAPI backend in dev mode (auto-reload)
make dev           # http://localhost:8000

# Run the frontend dev server
cd frontend && npm run dev   # http://localhost:5173

# Lint (ruff check + format check)
make lint

# Type-check (mypy strict)
make typecheck

# Run all backend + shared tests
make test
```

## Environment

Copy `backend/.env.example` to `backend/.env` and set:
- `APP_ENV` — defaults to `development`
- `DATABASE_URL` — defaults to `postgresql+psycopg://jobsearch:jobsearch@localhost:5432/jobsearch`

## Architecture

This is a `uv` workspace with three packages:

```
backend/   — FastAPI server (jobsearch-backend package)
shared/    — Pydantic contracts shared between backend and frontend (jobsearch-shared package)
frontend/  — Vite + React + TypeScript SPA (not a uv package)
```

**Backend layout** (`backend/app/`):
- `main.py` — FastAPI app factory; routers registered here
- `core/config.py` — Pydantic-Settings `Settings`; loaded from `backend/.env`
- `api/routes/` — one file per resource group (currently only `health.py`)
- `services/` — business logic
- `repositories/` — data access (SQLAlchemy)
- `models/` — SQLAlchemy ORM models
- `schemas/` — thin re-exports from `shared`
- `db/engine.py` — `DATABASE_URL`-driven engine + `get_session()`

**Database:** Postgres 16 + pgvector via Docker Compose. Backend is Postgres-only.

**Frontend layout** (`frontend/src/`):
- `api.ts` — typed fetch wrapper
- `pages/` — route components
- `components/` — shared UI

## Project Roadmap

The full PBI roadmap lives at `implementation_checklist/pbi_tracker.md`. The build order matters:

1. **Stage 1 — MVP (PBIs 1–5):** jobs schema → source ingestion → dedup keys → query routes → dashboard
2. **Stage 2 — Production engineering (PBIs 6–9):** crawl scheduler → failure recovery → "disappeared job" detection → observability
3. **Stage 3 — Search & ranking (PBIs 10–13):** full-text search → embeddings + pgvector → hybrid ranking → retrieval evaluation

## Code Quality

- Ruff enforces E/W/F/I/C/B rules, double quotes, 88-char line length (E501 ignored)
- Mypy runs in strict mode (`disallow_untyped_defs`, `no_implicit_optional`)
- Tests use in-memory SQLite for unit tests; Postgres is only exercised via Docker Compose
