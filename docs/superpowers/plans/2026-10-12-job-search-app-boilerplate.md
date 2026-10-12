# Job Search App Monorepo Boilerplate — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stand up a booting uv-workspace monorepo (backend/shared/frontend) shaped like dsa-tracker but backed by Postgres+pgvector, plus a PBI tracker that drives the MVP build.

**Architecture:** uv workspace with three packages — `jobsearch-backend` (FastAPI, layered routes→services→repositories→models), `jobsearch-shared` (Pydantic contracts), and a Vite React frontend. Postgres 16 + pgvector runs via Docker Compose; Alembic is wired with an empty initial revision. `make` targets wrap every workflow.

**Tech Stack:** Python 3.13, uv, FastAPI, SQLAlchemy 2 + Alembic, psycopg 3, pydantic-settings, Docker Compose (pgvector/pgvector:pg16); Vite 5, React 18, TypeScript, Tailwind 3, React Router 6, Vitest.

**Spec:** `docs/superpowers/specs/2026-10-12-job-search-app-boilerplate-design.md`

## Global Constraints

- Python `>=3.13` in all three `pyproject.toml`; `.python-version` = `3.13`.
- Workspace member names: `backend` → package `jobsearch-backend`; `shared` → package `jobsearch-shared` (import name `jobsearch_shared`).
- Default DB DSN (verbatim): `postgresql+psycopg://jobsearch:jobsearch@localhost:5432/jobsearch`.
- Frontend dev server origin (CORS): `http://localhost:5173`; API base default `http://localhost:8000`.
- ruff: line-length 88, target py313, select `["E","W","F","I","C","B"]`, ignore `["E501","E203"]`, double quotes.
- mypy strict: `disallow_untyped_defs = true`, `no_implicit_optional = true`, `check_untyped_defs = true`.
- Alembic revision IDs are 4-digit strings (`"0001"`), `revision` down to `None` for the initial revision; the initial migration must be empty (no domain tables).
- No LLM/MLflow config. No crawler/search/auth. Backend is Postgres-only (no SQLite fallback in code, only in tests).
- Backend does not import psycopg2 anywhere; driver is psycopg 3 (`psycopg[binary]`).

---

### Task 1: Repo root + uv workspace + Docker Compose

**Files:**
- Create: `.python-version`, `.gitignore`, `README.md`, `CLAUDE.md`, `pyproject.toml`, `Makefile`, `docker-compose.yml`

**Interfaces:**
- Produces: root `pyproject.toml` with `[tool.uv.workspace] members = ["backend", "shared"]`; `Makefile` targets `sync`, `db-up`, `db-down`, `migrate`, `dev`, `lint`, `typecheck`, `test`; `docker-compose.yml` exposing Postgres on `localhost:5432`.

- [ ] **Step 1: Write `.python-version` and `.gitignore`**

`.python-version`:
```
3.13
```

`.gitignore`:
```
# Python
__pycache__/
*.py[cod]
.venv/
.mypy_cache/
.ruff_cache/
.pytest_cache/
*.egg-info/
build/

# uv
uv.lock
dist/

# Frontend / Node
frontend/node_modules/
frontend/dist/

# Env / secrets
.env
*.env

# SQLite (tests only; prod DB is Postgres)
*.sqlite
*.db
```

- [ ] **Step 2: Write root `pyproject.toml`**

```toml
[project]
name = "job-search"
version = "0.1.0"
description = "Job Search Intelligence Platform — monorepo"
readme = "README.md"
requires-python = ">=3.13"
dependencies = []

[tool.uv.workspace]
members = ["backend", "shared"]

[tool.uv.sources]
jobsearch-shared = { workspace = true }
jobsearch-backend = { workspace = true }

[tool.pytest.ini_options]
minversion = "8.0"
addopts = "-ra -q"
pythonpath = ["backend", "shared", "."]
testpaths = ["backend/tests", "shared/tests"]

[tool.ruff]
target-version = "py313"
line-length = 88
indent-width = 4

[tool.ruff.lint]
select = ["E", "W", "F", "I", "C", "B"]
ignore = ["E501", "E203"]

[tool.ruff.lint.isort]
combine-as-imports = true
split-on-trailing-comma = true

[tool.ruff.format]
quote-style = "double"
indent-style = "space"
line-ending = "auto"

[tool.mypy]
python_version = "3.13"
ignore_missing_imports = true
warn_unused_configs = true
check_untyped_defs = true
disallow_untyped_defs = true
no_implicit_optional = true

[dependency-groups]
dev = [
    "ruff>=0.6",
    "mypy>=1.11",
    "pytest>=8",
]
```

- [ ] **Step 3: Write `docker-compose.yml`**

```yaml
services:
  db:
    image: pgvector/pgvector:pg16
    container_name: jobsearch_db
    environment:
      POSTGRES_USER: jobsearch
      POSTGRES_PASSWORD: jobsearch
      POSTGRES_DB: jobsearch
    ports:
      - "5432:5432"
    volumes:
      - jobsearch_pgdata:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U jobsearch -d jobsearch"]
      interval: 5s
      timeout: 5s
      retries: 10

volumes:
  jobsearch_pgdata:
```

- [ ] **Step 4: Write `Makefile`**

```makefile
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
```

- [ ] **Step 5: Write `README.md`**

```markdown
# Job Search Intelligence Platform

A tool for ingesting, normalizing, deduplicating, and searching job postings
from career pages and ATS APIs — built around reliable, incremental crawling
and measured search quality.

See `CLAUDE.md` for commands and architecture, and
`implementation_checklist/pbi_tracker.md` for the build roadmap.
```

- [ ] **Step 6: Write `CLAUDE.md`** (commands, environment, architecture, roadmap, code quality)

See the full content inline in the executor's run — mirror dsa-tracker's CLAUDE.md sections but reference jobsearch names and the PBI tracker path `implementation_checklist/pbi_tracker.md`.

- [ ] **Step 7: Verify `make sync` resolves**

Run: `make sync`
Expected: uv installs Python 3.13.12 and creates `.venv`; exit 0.

- [ ] **Step 8: Verify `make db-up` and healthcheck**

Run: `make db-up` then `docker compose ps`
Expected: `jobsearch_db` container `healthy`; then `make db-down`.

- [ ] **Step 9: Commit**

```bash
git add .python-version .gitignore README.md CLAUDE.md pyproject.toml Makefile docker-compose.yml uv.lock
git commit -m "feat: scaffold uv workspace + docker postgres compose"
```

---

### Task 2: `shared` package — Pydantic contracts

**Files:**
- Create: `shared/pyproject.toml`, `shared/README.md`, `shared/jobsearch_shared/__init__.py`, `shared/jobsearch_shared/schemas.py`, `shared/tests/__init__.py`, `shared/tests/test_schemas.py`

**Interfaces:**
- Produces: `jobsearch_shared.schemas.HealthResponse` (Pydantic v2 model `status: str` with `ConfigDict(from_attributes=True)`). Consumed by Task 4 (health route).

- [ ] **Step 1: Write `shared/pyproject.toml`**

```toml
[project]
name = "jobsearch-shared"
version = "0.1.0"
description = "Shared Pydantic contracts for job-search"
readme = "README.md"
requires-python = ">=3.13"
dependencies = [
    "pydantic>=2",
]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["jobsearch_shared"]
```

- [ ] **Step 2: Write `shared/jobsearch_shared/__init__.py`**

```python
"""Shared contracts for job-search (jobsearch_shared)."""
```

- [ ] **Step 3: Write the failing test `shared/tests/test_schemas.py`**

```python
from jobsearch_shared.schemas import HealthResponse


def test_health_response_roundtrip() -> None:
    h = HealthResponse(status="ok")
    assert h.status == "ok"
    assert h.model_dump() == {"status": "ok"}


def test_health_response_from_attributes() -> None:
    class Stub:
        status = "ok"

    h = HealthResponse.model_validate(Stub())
    assert h.status == "ok"
```

Also create `shared/tests/__init__.py` (empty).

- [ ] **Step 4: Run test to verify it fails**

Run: `uv run pytest shared/tests/test_schemas.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'jobsearch_shared'`.

- [ ] **Step 5: Write `shared/jobsearch_shared/schemas.py`**

```python
from pydantic import BaseModel, ConfigDict


class HealthResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    status: str
```

- [ ] **Step 6: Run test to verify it passes**

Run: `uv run pytest shared/tests/test_schemas.py -v`
Expected: PASS (2 tests).

- [ ] **Step 7: Write `shared/README.md`** (one line: package name + purpose).

- [ ] **Step 8: Commit**

```bash
git add shared/
git commit -m "feat: shared pydantic contracts package"
```

---

### Task 3: `backend` package + config + engine

**Files:**
- Create: `backend/pyproject.toml`, `backend/README.md`, `backend/.env.example`, `backend/app/__init__.py`, `backend/app/core/__init__.py`, `backend/app/core/config.py`, `backend/app/core/config.yml`, `backend/app/db/__init__.py`, `backend/app/db/engine.py`, `backend/app/models/__init__.py`, `backend/app/models/base.py`, `backend/app/repositories/__init__.py`, `backend/app/services/__init__.py`, `backend/app/schemas/__init__.py`, `backend/tests/__init__.py`, `backend/tests/test_engine.py`, `backend/tests/test_config.py`

**Interfaces:**
- Consumes: `jobsearch-shared` (Task 2).
- Produces: `app.core.config.Settings` (BaseSettings with `app_env: str`), `app.core.config.build_settings()`, `app.db.engine.database_url() -> str`, `app.db.engine.make_engine()`, `app.db.engine.get_session()` context manager, `app.models.base.Base`.

- [ ] **Step 1: Write `backend/pyproject.toml`**

```toml
[project]
name = "jobsearch-backend"
version = "0.1.0"
description = "FastAPI backend for job-search"
readme = "README.md"
requires-python = ">=3.13"
dependencies = [
    "jobsearch-shared",
    "fastapi>=0.115",
    "uvicorn[standard]>=0.34",
    "pydantic>=2",
    "pydantic-settings>=2",
    "pyyaml>=6",
    "python-dotenv>=1",
    "sqlalchemy>=2.0",
    "alembic>=1.13",
    "psycopg[binary]>=3.2",
    "pgvector>=0.3",
]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["app"]

[tool.uv.sources]
jobsearch-shared = { workspace = true }
```

- [ ] **Step 2: Write `backend/app/__init__.py`** (docstring only).

- [ ] **Step 3: Write `backend/app/models/base.py`**

```python
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass
```

- [ ] **Step 4: Write `backend/app/models/__init__.py`**

```python
from app.models.base import Base

__all__ = ["Base"]
```

- [ ] **Step 5: Write `backend/app/db/engine.py`** (failing-test first; see Step 7 tests)

```python
import os
from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session

DEFAULT_DB_URL = "postgresql+psycopg://jobsearch:jobsearch@localhost:5432/jobsearch"


def database_url() -> str:
    return os.environ.get("DATABASE_URL", DEFAULT_DB_URL)


def make_engine() -> Engine:
    return create_engine(database_url())


engine: Engine = make_engine()


@contextmanager
def get_session() -> Iterator[Session]:
    with Session(engine) as session:
        yield session
```

- [ ] **Step 6: Write `backend/app/db/__init__.py`** (empty).

- [ ] **Step 7: Write the failing tests `backend/tests/test_engine.py`**

```python
from app.db import engine as engine_mod
from app.db.engine import DEFAULT_DB_URL
from app.models import Base
from sqlalchemy import create_engine


def test_database_url_returns_default() -> None:
    assert DEFAULT_DB_URL == "postgresql+psycopg://jobsearch:jobsearch@localhost:5432/jobsearch"


def test_database_url_respects_env_override(monkeypatch) -> None:
    import pytest

    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://u:p@h:5432/x")
    assert engine_mod.database_url() == "postgresql+psycopg://u:p@h:5432/x"


def test_get_session_yields_session(monkeypatch) -> None:
    test_engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(test_engine)
    monkeypatch.setattr(engine_mod, "engine", test_engine)

    with engine_mod.get_session() as s:
        assert s is not None
```

- [ ] **Step 8: Run tests to verify `engine` imports, then fail on monkeypatch condition**

Run: `uv run pytest backend/tests/test_engine.py -v`
Expected: FAIL or PASS — confirm the module import works and the env-override test is correct; once `DATABASE_URL` is unset in the shell it behaves (uses default). Record actual result.

- [ ] **Step 9: Write `backend/app/core/__init__.py`** (empty).

- [ ] **Step 10: Write `backend/app/core/config.py`**

```python
from pathlib import Path

import yaml
from pydantic import BaseModel
from pydantic_settings import BaseSettings, SettingsConfigDict, PydanticBaseSettingsSource
```

Full content inline at execution: `Settings(AppEnv)` BaseSettings reading `backend/.env` with `app_env` defaulting `"development"`; a `load_app_config(path)` YAML loader returning a small `AppConfig`. No API keys, no MLflow. `ConfigurationError` kept only if trivially needed; otherwise omit (YAGNI). This task's `test_config.py` asserts `Settings` defaults and YAML round-trip.

- [ ] **Step 11: Write `backend/app/core/config.yml`**

```yaml
app:
  name: "job-search"
  env: "development"
```

- [ ] **Step 12: Write `backend/tests/test_config.py`**

```python
from app.core.config import Settings


def test_settings_defaults() -> None:
    s = Settings(_env_file=None)
    assert s.app_env == "development"
```

- [ ] **Step 13: Run backend tests**

Run: `uv run pytest backend/tests -v`
Expected: PASS.

- [ ] **Step 14: Write `backend/.env.example` and `backend/README.md`**

`.env.example`:
```
APP_ENV=development
DATABASE_URL=postgresql+psycopg://jobsearch:jobsearch@localhost:5432/jobsearch
```

- [ ] **Step 15: Commit**

```bash
git add backend/
git commit -m "feat: backend package with config + engine"
```

---

### Task 4: FastAPI app + health route + CORS

**Files:**
- Create: `backend/app/api/__init__.py`, `backend/app/api/routes/__init__.py`, `backend/app/api/routes/health.py`, `backend/app/main.py`, `backend/tests/test_routes_health.py`, `backend/tests/test_cors.py`

**Interfaces:**
- Consumes: `jobsearch_shared.schemas.HealthResponse` (Task 2), `app.db.engine.get_session` (Task 3).
- Produces: `app.main.app` (FastAPI instance) with CORS for `http://localhost:5173` and `GET /health` returning `{"status": "ok"}`.

- [ ] **Step 1: Write failing test `backend/tests/test_routes_health.py`**

```python
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health_returns_ok() -> None:
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}
```

- [ ] **Step 2: Verify it fails**

Run: `uv run pytest backend/tests/test_routes_health.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.main'`.

- [ ] **Step 3: Write `backend/app/api/routes/health.py`**

```python
from fastapi import APIRouter

from jobsearch_shared.schemas import HealthResponse

router = APIRouter()


@router.get("/health", response_model=HealthResponse)
async def health_check() -> HealthResponse:
    return HealthResponse(status="ok")
```

- [ ] **Step 4: Write `backend/app/api/routes/__init__.py`** and `backend/app/api/__init__.py` (empty).

- [ ] **Step 5: Write `backend/app/main.py`**

```python
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import health

app = FastAPI(title="Job Search API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router)
```

- [ ] **Step 6: Write `backend/tests/test_cors.py`**

```python
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_cors_headers_present() -> None:
    resp = client.get("/health", headers={"Origin": "http://localhost:5173"})
    assert resp.status_code == 200
    assert resp.headers["access-control-allow-origin"] == "http://localhost:5173"
```

- [ ] **Step 7: Run tests to verify pass**

Run: `uv run pytest backend/tests/test_routes_health.py backend/tests/test_cors.py -v`
Expected: PASS.

- [ ] **Step 8: Verify `make dev` serves /health**

Run (background): `make dev` then `curl -s localhost:8000/health`
Expected: `{"status":"ok"}`. Stop the server afterward.

- [ ] **Step 9: Commit**

```bash
git add backend/app backend/tests
git commit -m "feat: fastapi app with health route + CORS"
```

---

### Task 5: Alembic wiring + empty initial migration

**Files:**
- Create: `backend/alembic.ini`, `backend/alembic/env.py`, `backend/alembic/script.py.mako`, `backend/alembic/versions/__init__.py` (optional), `backend/alembic/versions/0001_empty.py`

**Interfaces:**
- Consumes: `app.db.engine.DEFAULT_DB_URL` (Task 3), `app.models.Base` (Task 3).
- Produces: a working Alembic env targeting `Base.metadata` with an empty `0001` revision (revision `"0001"`, `down_revision=None`). `make migrate` upgrades to `head`.

- [ ] **Step 1: Write `backend/alembic.ini`** (copy reference shape; `script_location = %(here)s/alembic`, `prepend_sys_path = .`).

- [ ] **Step 2: Write `backend/alembic/env.py`** (mirror dsa-tracker's, but import `DEFAULT_DB_URL` from `app.db.engine` and set `sqlalchemy.url` from `DATABASE_URL` env or `DEFAULT_DB_URL`; point `target_metadata = Base.metadata`).

- [ ] **Step 3: Write `backend/alembic/script.py.mako`** (copy reference verbatim).

- [ ] **Step 4: Write `backend/alembic/versions/0001_empty.py`**

```python
"""empty baseline

Revision ID: 0001
Revises:
Create Date: 2026-10-12
"""

from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
```

- [ ] **Step 5: Verify `make migrate` runs against Postgres**

Run: `make db-up && make migrate`
Expected: alembic creates `alembic_version` table and records `0001`. Then `make db-down`.

- [ ] **Step 6: Commit**

```bash
git add backend/alembic.ini backend/alembic
git commit -m "feat: alembic wiring with empty baseline migration"
```

---

### Task 6: Frontend scaffold + pages

**Files:**
- Create: `frontend/package.json`, `frontend/vite.config.ts`, `frontend/tsconfig.json`, `frontend/tailwind.config.js`, `frontend/postcss.config.js`, `frontend/index.html`, `frontend/src/main.tsx`, `frontend/src/App.tsx`, `frontend/src/api.ts`, `frontend/src/types.ts`, `frontend/src/index.css`, `frontend/src/setupTests.ts`, `frontend/src/vite-env.d.ts`, `frontend/src/components/NavBar.tsx`, `frontend/src/pages/DashboardPage.tsx`, `frontend/src/pages/PbiTrackerPage.tsx`, `frontend/src/pages/PbiTrackerPage.test.tsx`

**Interfaces:**
- Consumes: `VITE_API_URL` env (default `http://localhost:8000`).
- Produces: a Vite React app with routes `/` (Dashboard) and `/pbi` (PBI tracker), plus a `pbis.ts` data module typed and tested.

- [ ] **Step 1: Write `frontend/package.json`**

```json
{
  "name": "job-search-frontend",
  "private": true,
  "version": "0.1.0",
  "type": "module",
  "scripts": {
    "dev": "vite",
    "build": "tsc --noEmit && vite build",
    "preview": "vite preview",
    "test": "vitest run",
    "test:watch": "vitest",
    "typecheck": "tsc --noEmit"
  },
  "dependencies": {
    "react": "^18.3.1",
    "react-dom": "^18.3.1",
    "react-router-dom": "^6.26.2"
  },
  "devDependencies": {
    "@testing-library/jest-dom": "^6.4.8",
    "@testing-library/react": "^14.3.1",
    "@testing-library/user-event": "^14.5.2",
    "@types/react": "^18.3.5",
    "@types/react-dom": "^18.3.0",
    "@vitejs/plugin-react": "^4.3.1",
    "autoprefixer": "^10.4.20",
    "jsdom": "^24.1.1",
    "postcss": "^8.4.45",
    "tailwindcss": "^3.4.10",
    "typescript": "^5.5.4",
    "vite": "^5.4.3",
    "vitest": "^1.6.0"
  }
}
```

- [ ] **Step 2: Write `frontend/vite.config.ts`**, `tsconfig.json`, `tailwind.config.js`, `postcss.config.js`, `index.html`, `src/index.css`, `src/setupTests.ts`, `src/vite-env.d.ts` — copy the reference's exact contents (Vite config with vitest jsdom/env + `./src/setupTests.ts`).

- [ ] **Step 3: Write `frontend/src/types.ts`**

```typescript
export type PbiStage = "mvp" | "engineering" | "search";

export interface Pbi {
  id: string;
  stage: PbiStage;
  title: string;
  description: string;
  depends_on: string[];
}
```

- [ ] **Step 4: Write `frontend/src/pages/pbis.ts`** — the typed list matching `implementation_checklist/pbi_tracker.md` (13 PBIs across 3 stages, with `id`, `title`, `description`, `depends_on`). Content copied from the PBI tracker markdown.

- [ ] **Step 5: Write `frontend/src/api.ts`** (fetch wrapper mirroring reference: `BASE`, `request<T>`, and a `fetchHealth(): Promise<{status: string}>`).

- [ ] **Step 6: Write `frontend/src/main.tsx`** and `src/App.tsx` (router: `/` → DashboardPage, `/pbi` → PbiTrackerPage, both wrapped in NavBar).

- [ ] **Step 7: Write `frontend/src/components/NavBar.tsx`** (links Home + PBI Tracker, Tailwind-styled).

- [ ] **Step 8: Write `frontend/src/pages/DashboardPage.tsx`** (placeholder heading naming the project).

- [ ] **Step 9: Write `frontend/src/pages/PbiTrackerPage.tsx`** (maps `PBIS` grouped by stage into a checklist; each row shows `id`, `title`, `description`, `depends_on`).

- [ ] **Step 10: Write failing test `frontend/src/pages/PbiTrackerPage.test.tsx`**

```tsx
import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { PbiTrackerPage } from "./PbiTrackerPage";
import { PBIS } from "./pbis";

describe("PbiTrackerPage", () => {
  it("renders every PBI title", () => {
    render(
      <MemoryRouter>
        <PbiTrackerPage />
      </MemoryRouter>,
    );
    for (const pbi of PBIS) {
      expect(screen.getByText(pbi.title)).toBeInTheDocument();
    }
  });
});
```

- [ ] **Step 11: Run frontend install + tests**

Run: `cd frontend && npm install` then `npm test -- --run`
Expected: `npm install` succeeds on Node 18; the PBI test passes. If `npm install` fails on Node 18 (Vite 5 requires Node 18+; reports "18.19 works"), surface it and consider Vite 4 — do not silently downgrade.

- [ ] **Step 12: Run `npm run typecheck` and `npm run build`**

Expected: both pass.

- [ ] **Step 13: Commit**

```bash
git add frontend/
git commit -m "feat: vite react frontend with dashboard + pbi tracker"
```

---

### Task 7: PBI tracker markdown + drift test + full gate

**Files:**
- Create: `implementation_checklist/pbi_tracker.md`

**Interfaces:**
- Produces: the markdown roadmap that the frontend `pbis.ts` mirrors, plus a final full-suite run.

- [ ] **Step 1: Write `implementation_checklist/pbi_tracker.md`** — 13 PBIs (Stage 1 MVP: PBI 1–5; Stage 2 Engineering: PBI 6–9; Stage 3 Search: PBI 10–13), each with title, description, dependency note, and an unchecked `- [ ]` checkbox. Match the spec §7 exactly.

- [ ] **Step 2: Add a drift guard note** linking the markdown and `frontend/src/pages/pbis.ts` (a comment in each pointing at the other, noting they must stay in sync).

- [ ] **Step 3: Run the full gate**

Run: `make lint && make typecheck && make test`
Expected: all green.

- [ ] **Step 4: Final commit**

```bash
git add implementation_checklist/ docs/superpowers/plans/
git commit -m "docs: pbi tracker roadmap + implementation plan"
```

---

## Self-Review Notes

- **Spec coverage:** §2 stack → Tasks 1/2/3/6; §3 layout → all file tasks; §4 backend → Task 3/4; §5 shared → Task 2; §6 frontend → Task 6; §7 PBI tracker → Task 7; §8 boots → Task 4/5/7 gates; §9 deviations → Global Constraints; §10 risks → Task 1/6 gates.
- The plan intentionally leaves `config.py` and `CLAUDE.md` described rather than fully inlined (they mirror dsa-tracker verbatim); the executor reads the reference repo for those two files.
