# Job Search Intelligence Platform

A tool for ingesting, normalizing, deduplicating, and searching job postings from
official feed sources (career pages, ATS APIs) — built around reliable, incremental
crawling and measured search quality.

The MVP (Stage 1) is complete: a `jobs` schema, a source-ingestion pipeline with a
canonical dedup identity, query routes, and a filterable dashboard. See the
[roadmap](#roadmap) below for what's next.

## Features

- **Source ingestion** — a `JobSource` abstraction crawls permitted feeds (Google
  Careers today) and upserts jobs into Postgres via an idempotent `IngestionService`.
- **Canonical identity** — jobs are deduplicated on `(source, external_job_id)` with a
  partial unique index; re-crawls bump `last_seen_at` instead of creating duplicates.
- **Query API** — list/detail endpoints with `source`, `company`, `location`, and
  full-text `q` filters, server-side `limit`/`offset` pagination, and a `total` count.
- **Dashboard** — a React SPA to browse, filter, and inspect job postings, plus a
  live rendering of the build roadmap.
- **Quality gates** — Ruff, mypy (strict), and pytest on every layer (unit + opt-in
  network integration tests).

## Architecture

A `uv` workspace monorepo with three packages plus a Postgres 16 + pgvector database:

```
backend/   — FastAPI server (jobsearch-backend package)
shared/    — Pydantic contracts shared across backend/frontend (jobsearch-shared)
frontend/  — Vite + React + TypeScript SPA (not a uv package)
```

| Layer | Path | Responsibility |
| --- | --- | --- |
| Routes | `backend/app/api/routes/` | HTTP handlers (health, jobs list/detail) |
| Services | `backend/app/services/` | Business logic |
| Ingestion | `backend/app/ingestion/` | Fetch → normalize → upsert pipeline; `sources/` and `spiders/` |
| Repositories | `backend/app/repositories/` | SQLAlchemy data access |
| Models | `backend/app/models/` | SQLAlchemy ORM models (`jobs`) |
| Schemas | `backend/app/schemas/` + `shared/` | Re-exports of the shared Pydantic contracts |

**Database** — Postgres 16 + pgvector via Docker Compose. The backend is Postgres-only;
unit tests run against in-memory SQLite, and Postgres is exercised via the Docker Compose
service (integration tests) or manual migration.

**Data flow** — a source (e.g. Google Careers sitemap) yields job drafts; normalization
happens at the ingest boundary; `IngestionService` upserts each draft against the
`(source, external_job_id)` identity, creating new rows and bumping `last_seen_at` on
re-sightings.

## Quick start

```bash
# Install all workspace dependencies
make sync

# Start Postgres + pgvector
make db-up

# Apply migrations
make migrate

# Copy and edit environment (defaults target the Compose DB)
cp backend/.env.example backend/.env

# Run the API (http://localhost:8000)
make dev

# Run the dashboard (http://localhost:5173) — in a second terminal
cd frontend && npm install && npm run dev
```

### Ingest jobs

```bash
# One-shot ingestion from the configured source (opt-in network access)
make ingest                 # trigger=manual (default)
make ingest TRIGGER=cron    # trigger=cron, as the crontab uses
```

Every attempt that reaches the app writes one `crawl_runs` row (`running` →
`succeeded` | `failed`, or `skipped_locked`). Exit codes: **0** success, **1**
crawl failed, **2** skipped because another run holds the advisory lock.

#### Scheduling with cron

The cadence's single source of truth is `SCHEDULE` in
`backend/app/ingestion/schedule.py` (currently `17 6 * * *`, daily at 06:17
host-local). Add the matching line with `crontab -e`:

```
17 6 * * * cd /home/jason/job-search && /usr/bin/make ingest TRIGGER=cron >> /var/log/jobsearch-ingest.log 2>&1
```

Update the README line together with `SCHEDULE` — a drifted README is how a
cadence silently changes.

**Gotchas**

- Use absolute paths (`which make uv docker`); cron's `PATH` is minimal.
- The Docker daemon must be up for Postgres. A precheck is recommended:
  `docker compose ps --status running`.
- The log file must be writable by the cron user.
- **A run whose process never started is not recorded.** The DB record covers
  attempts that reached the app; a cron entry that fails to launch (Docker down,
  bad path) shows only in the log. Host-level metrics (PBI 9) close that gap.
- **Missed runs are tolerated, not backfilled.** Laptop asleep at 06:17 means no
  crawl that day; the next run catches up on data. PBI 8 therefore keys
  "disappeared" off observed successful runs, never wall-clock days.

#### Politeness and scope

Request rate is pinned in `backend/app/ingestion/scrapy_settings.py` from the
per-host budgets in `ingestion/policy.py` (2s delay, one request in flight,
autothrottle on, `RETRY_TIMES=0`). `PolicyGuardMiddleware` (a Scrapy spider
middleware) raises `PolicyViolation` and stops the crawl if the spider ever
requests a URL that is not a sitemap `<loc>` — the crawl cannot silently widen
its scope.

## API

| Method | Path | Description |
| --- | --- | --- |
| GET | `/health` | Liveness check |
| GET | `/jobs` | List jobs with `limit`/`offset` (`1–100`, default 50) and optional `source`, `company`, `location`, `q` filters |
| GET | `/jobs/{job_id}` | Single job detail |

Responses use the shared `JobResponse` / `JobListResponse` contracts
(`shared/jobsearch_shared/schemas.py`).

## Development

```bash
make lint         # ruff check + format check
make typecheck    # mypy strict
make test         # backend + shared unit tests (skips network)
make test-integration  # opt-in network tests (live sitemap fetch)
```

Frontend equivalents:

```bash
cd frontend
npm run typecheck   # tsc --noEmit
npm test            # vitest
npm run build       # typecheck + production build
```

Quality standards are enforced in `pyproject.toml`: Ruff (double quotes, 88-char lines,
E/W/F/I/C/B rules), mypy in strict mode, and pytest with in-memory SQLite for unit tests.

## Roadmap

The build roadmap lives at `implementation_checklist/pbi_tracker.md` (also rendered in
the dashboard at `/pbi`). Build order matters — each stage ships working, tested software.

- **Stage 1 — MVP** ✅ Jobs schema → source ingestion → dedup keys → query routes → dashboard.
- **Stage 2 — Production engineering** Crawl scheduler, failure recovery, disappeared-job
  detection, observability.
- **Stage 3 — Search & ranking** Full-text search, embeddings + pgvector, hybrid ranking +
  resume matching, retrieval-quality evaluation.

## License

Private prototype — see `implementation_checklist/pbi_tracker.md` for scope.
