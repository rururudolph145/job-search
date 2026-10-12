# Job Search Intelligence Platform — Monorepo Boilerplate Design

**Date:** 2026-10-12
**Status:** Approved (pending spec review)
**Scope:** Scaffolding only — a booting monorepo skeleton plus a PBI tracker. Not the crawler.

## 1. Purpose

Stand up a monorepo for a **Job Search Intelligence Platform** — a tool that ingests
job postings from career pages and ATS APIs, normalizes and deduplicates them, indexes
them for keyword and semantic search, and surfaces matches in a dashboard.

The end goal is production-shaped engineering (reliable, incremental crawling; correct
"is this job gone?" semantics; measured freshness and retrieval quality), not another
LLM PoC. The immediate priority is a genuinely useful daily job-hunting tool, evolved
into a portfolio-grade system.

**This spec delivers the skeleton only.** It produces a monorepo that boots
end-to-end, with the same shape and conventions as the `dsa-tracker` reference project,
plus a PBI tracker that drives the real MVP build in later specs. No crawler, no search
index, no LLM matching, and no authentication are built here.

## 2. Stack

Mirrored from `dsa-tracker`, with a Postgres pivot.

| Layer | dsa-tracker | This project |
|---|---|---|
| Workspace | uv workspace, 3 packages | same (`backend`, `shared`, `frontend`) |
| Backend | FastAPI + SQLAlchemy 2 + Alembic + Pydantic-Settings | same |
| Database | SQLite (`~/.dsa-tracker/db.sqlite`) | **Postgres 16 + pgvector via Docker Compose** |
| DB driver | (none — SQLite) | `psycopg[binary]>=3.2` (psycopg 3, 3.13-clean) |
| Frontend | Vite 5 + React 18 + TS + Tailwind 3 + React Router 6 + Vitest | same |
| Quality | ruff (E/W/F/I/C/B, 88 cols) + mypy strict + pytest; `make` targets | same |
| Python | `>=3.13` | `>=3.13` (local CPython 3.13.12 via uv) |

**Python 3.13 verification.** The local machine already has CPython 3.13.12 installed
via uv (`/home/jason/.local/share/uv/python/cpython-3.13-linux-x86_64-gnu`) — the same
interpreter `dsa-tracker`'s `.venv` uses. Every dependency in the stack supports 3.13:
fastapi/starlette/pydantic-v2 (3.13 wheels for pydantic-core), SQLAlchemy 2, Alembic,
uvicorn, pytest 8, ruff, mypy, pgvector (pure Python), and psycopg 3. `make sync` runs
as the first verification gate so any resolution problem surfaces before app code is
written. `psycopg[binary]` (v3) is specified from the start to avoid the well-known
`psycopg2` 3.13 build failure.

## 3. Repository layout

```
job-search/
  docker-compose.yml          # postgres (pgvector/pgvector:pg16) + healthcheck
  pyproject.toml              # uv workspace root: ruff/mypy/pytest config
  Makefile                    # sync, db-up, db-down, migrate, dev, lint, typecheck, test
  .gitignore  .python-version  README.md  CLAUDE.md
  backend/
    pyproject.toml            # jobsearch-backend
    alembic.ini  alembic/{env.py,script.py.mako,versions/}
    .env.example  README.md
    app/
      main.py                 # app factory + CORS + router registration
      core/{config.py,config.yml}
      db/engine.py            # DATABASE_URL-driven engine + get_session
      api/routes/{__init__.py,health.py}
      models/{__init__.py,base.py}
      repositories/__init__.py
      services/__init__.py
      schemas/                # thin re-exports from shared
    tests/{__init__.py,test_engine.py,test_routes_health.py,test_cors.py,test_models.py}
  shared/
    pyproject.toml            # jobsearch-shared
    jobsearch_shared/{__init__.py,schemas.py}
    tests/{__init__.py,test_schemas.py}
  frontend/
    index.html  package.json  vite.config.ts  tsconfig.json
    tailwind.config.js  postcss.config.js
    src/{main.tsx,App.tsx,api.ts,types.ts,index.css,setupTests.ts}
    src/components/NavBar.tsx
    src/pages/{DashboardPage.tsx,PbiTrackerPage.tsx}
  docs/superpowers/specs/   # this spec
  implementation_checklist/pbi_tracker.md
```

## 4. Backend architecture

The layered flow is preserved from the reference: **routes → services → repositories →
models**, with Pydantic contracts living in `shared`.

- `app/main.py` — creates the FastAPI app, registers CORS for `http://localhost:5173`,
  and includes routers. This pass includes only the health router.
- `app/core/config.py` — Pydantic-Settings `Settings` loaded from `backend/.env`, plus a
  YAML `AppConfig` loader mirroring the reference's `ConfigurationError` startup contract.
  No LLM/MLflow config in this pass.
- `app/db/engine.py` — `DATABASE_URL`-driven engine factory. Defaults to the Compose
  DSN (`postgresql+psycopg://jobsearch:jobsearch@localhost:5432/jobsearch`); env override
  preserved. `get_session()` context manager yields a `Session`, as in the reference.
- `app/api/routes/health.py` — `GET /health` → `{"status": "ok"}`.
- `app/models/base.py` — `Base(DeclarativeBase)`; no domain tables yet (they arrive with PBI 1).
- Layered packages exist and are importable but empty, so PBIs land into a known shape.

## 5. Shared contracts

`shared/jobsearch_shared/schemas.py` holds Pydantic v2 contracts shared between backend
and a future typed frontend. This pass defines only the small primitives the skeleton
needs (e.g. a `HealthResponse`), so the cross-package import path and workspace wiring
are proven by a real test rather than asserted.

## 6. Frontend architecture

Vite + React 18 + TypeScript, mirroring the reference (`createBrowserRouter`, `NavBar`,
`api.ts` fetch wrapper with a typed error hierarchy, Tailwind for styling, Vitest +
Testing Library for tests).

Two pages:

- `DashboardPage` — a placeholder shell at `/` that confirms the stack renders and names
  the project. Domain content arrives with its PBIs.
- `PbiTrackerPage` at `/pbi` — renders the PBI tracker content, so build order is
  visible in the app itself. `implementation_checklist/pbi_tracker.md` and this page are
  two copies of one list; a test pins them together (§10) so they cannot drift unnoticed.

## 7. The PBI tracker

Modeled on `dsa-tracker`'s `implementation_checklist/pbi_tracker.md`: a markdown
checklist of PBIs with dependencies, doubling as the spec-selection menu for later
brainstorm cycles. Backend-first ordering, following the prioritization agreed during
brainstorming.

### Stage 1 — MVP (the useful tool)

- **PBI 1** — Jobs schema: `jobs`, `companies`, `job_sources` tables + Alembic migration + repositories.
- **PBI 2** — Source ingestion: fetch from official job APIs / permitted feeds only (no bot-protection bypass).
- **PBI 3** — Normalization + dedup keys: canonical job identity across URLs and ATS providers.
- **PBI 4** — Query routes: list/detail/filter endpoints for jobs.
- **PBI 5** — Jobs dashboard page: browse, filter, and open job details.

### Stage 2 — Production engineering

- **PBI 6** — Crawl scheduler + per-host rate limits + robots.txt/policy compliance.
- **PBI 7** — Failure recovery: retry with exponential backoff; idempotent writes on retry.
- **PBI 8** — "Disappeared job" detection: repeated-confirmation rule; distinguish a failed fetch from a successful empty response.
- **PBI 9** — Observability: crawl success, freshness, latency, and error metrics.

### Stage 3 — Search & ranking

- **PBI 10** — Keyword full-text search.
- **PBI 11** — Embeddings + pgvector semantic retrieval; incremental re-indexing of changed documents.
- **PBI 12** — Hybrid ranking + resume-to-job matching; explainable ranking and filters.
- **PBI 13** — Retrieval-quality evaluation + index-freshness measurement.

Each PBI carries a short description and a dependency note (e.g. "depends on PBI 1").
The tracker is the input to the next brainstorming cycle; it is not implemented in this
spec.

## 8. Vertical-slice proof of "it boots"

- `make db-up` starts Postgres+pgvector; the Compose healthcheck passes.
- Alembic is wired and runs an **empty initial revision** (domain schema lands with PBI 1).
- `make dev` serves `GET /health` on `:8000`; FastAPI `/docs` renders.
- `make test` runs backend tests (engine URL contract, health route, CORS, models import),
  shared tests (cross-package schema import), and frontend Vitest — all green.
- `make lint` (ruff check + format check) and `make typecheck` (mypy strict + `tsc --noEmit`) pass.
- Frontend boots on `:5173`, rendering NavBar + Dashboard placeholder + PBI Tracker page.
- Docker Compose is the only DB provisioning; `DATABASE_URL` defaults to the Compose DSN
  and is env-overridable.

## 9. Deliberate deviations from the reference

1. **Postgres over SQLite** — `db/engine.py` keeps the reference's `DATABASE_URL`
   env-override contract but defaults to the Compose DSN; driver is psycopg 3.
2. **No LLM/MLflow config** — omitted entirely in this pass; pgvector takes the
   embedding-store role and is wired in PBI 11.
3. **Two frontend pages instead of three** — Dashboard placeholder + PBI Tracker;
   domain pages arrive with their PBIs.
4. **New CLAUDE.md** — written for this project (map, commands, tracker pointer), not copied.
5. **Empty package scaffolding** — `repositories/`, `services/`, `schemas/`, and `models/`
   (beyond `base.py`) exist but are empty, so PBIs land into a known shape.

## 10. Risks and mitigations

- **Dependency resolution on 3.13** — mitigated by running `make sync` as the first
  implementation gate before app code; any failure is reported, not silently pinned around.
- **`pgvector/pgvector:pg16` image pull** — requires network on first `make db-up`; Docker
  is confirmed running and ports 5432/8000/5173 are free.
- **Node 18.19 vs Vite 5** — the reference pins Vite 5.4 / Vitest 1.6 and works on Node 18;
  if `npm install` trips on Node 18, the fallback is Vite 4 and it will be surfaced rather
  than applied silently.
- **Tracker content duplication** — the markdown file and the `PbiTrackerPage` data are two
  copies of one list; a test pins them together so they cannot drift unnoticed.

## 11. Out of scope

Crawling, scheduling, deduplication logic, search, embeddings, ranking, authentication,
deployment, and CI. Each is owned by a PBI above.
