# System Sketch — Ingestion to Serving (PBIs 1–6)

> Status: reference (as-built snapshot)
> Date: 2026-11-16
> Covers: PBI 1 (jobs schema), PBI 2 (source ingestion), PBI 3 (normalization +
> dedup), PBI 4 (query routes), PBI 5 (dashboard), PBI 6 (crawl scheduler)
> Audience: someone who needs the whole picture in one page before reading any
> per-PBI spec.

## 1. Top-level shape

Two processes, one database. The **crawler** is a one-shot CLI run by cron; the
**API** is a long-lived server. They never talk directly — they meet at Postgres.

```
        ┌─────────────────────── INGESTION (write path, offline) ───────────────────────┐
        │                                                                               │
 cron / make ingest                                                                     │
 (17 6 * * *, §6.9)                                                                     │
        │                                                                               │
        ▼                                                                               │
 python -m app.ingest ──► IngestRun ──► advisory lock ─► crawl_runs: running ─► Crawl+Upsert ─► mark success/failed
 (backend/app/ingest.py)   (run.py)     (locking.py)    (crawl_run.py)             │              │
                                                                                    ▼              ▼
                                                                            Scrapy crawl     jobs table
                                                                            Google Careers   (Postgres 16)
                                                                                  │
                                                                                  ▼
                                                                             Postgres 16
        └───────────────────────────────────────────────────────────────────────────────┘
                                         │
                         ┌───────────────┴───────────────┐
                         ▼                               ▼
                 FastAPI  /jobs, /jobs/{id}       React dashboard (:5173)
```

## 2. Write path: the crawl (PBIs 2, 3, 6)

### 2.1 Entry — `python -m app.ingest --trigger {cron,manual}`

`backend/app/ingest.py`

- Builds a `GoogleCareersSource` via a `build_source()` seam (faked in tests).
- Builds a `Session` factory from `make_engine()` (`DATABASE_URL`-driven).
- Calls `IngestRun(source, session_factory, trigger).run()` and maps the
  outcome to an exit code: **0** success, **1** crawl failed, **2** skipped
  (another run holds the lock).

### 2.2 Orchestrator — `IngestRun.run()`

`backend/app/ingestion/run.py` — the PBI 6 core.

- Takes one clock reading (`now`) reused for the run row *and* every job
  timestamp.
- Acquires the **Postgres advisory lock** (`ingestion_lock`, `locking.py`, key
  `0x4A530006`) — non-blocking `pg_try_advisory_lock`; SQLite always yields
  `True`. If not held → writes a `skipped_locked` row, returns exit 2.
- Writes a `crawl_runs` row `running`, **commits before crawling** — so a
  mid-crawl crash leaves a `running` row with `finished_at IS NULL` (the
  deliberate "crawl died" signal PBI 8 will read).
- Runs `IngestionService.run(session)`. On any exception: `rollback()` (discard
  partial job writes), record `failed` + error on a clean transaction, exit 1.
  On success: record `succeeded` + counters, exit 0.
- Lock released in `finally` (only if this call acquired it).

### 2.3 Fetch — `GoogleCareersSource.fetch()`

`backend/app/ingestion/sources/`

- The `JobSource` protocol is the seam: `name`, `skipped_no_id`,
  `fetch() -> Iterator[JobDraft]`.
- Runs a **Scrapy** crawl (`CrawlerProcess`) with settings pinned from per-host
  budgets (`scrapy_settings.py` ← `policy.py`): 2s download delay, 1 concurrent
  request, autothrottle on, `RETRY_TIMES=0` (retry is PBI 7),
  `ROBOTSTXT_OBEY=False`.
- **Spider** (`spiders/google_careers.py`): starts at the sitemap, keeps only
  `software-engineer` `<loc>` URLs, records them in `allowed_sitemap_urls`,
  then fetches each detail page. A page with **no Tokyo-metro location term**
  is filtered out (yields nothing).
- **`PolicyGuardMiddleware`** (`middleware.py`, a spider middleware): snapshots
  the permitted scope on the *first output item*, then raises `PolicyViolation`
  (stops the crawl) if any request URL — or a redirect target whose origin is
  out of scope — escapes the sitemap `<loc>` set. Redirect targets are allowed
  only when redirected *from* an in-scope loc.
- Raw spider dicts are collected via `_CrawlItemsPipeline` into a module list,
  drained by `_run_crawl`. Network failure → `FetchError` (distinguishable from
  an empty-but-successful crawl).
- `fetch()` **normalizes** each raw dict (`normalize.py`: NFKC + whitespace
  collapse; `external_job_id` empty → dropped, `skipped_no_id++`) and yields a
  frozen `JobDraft(external_job_id, title, company, location, url)`.

### 2.4 Upsert — `IngestionService.run()`

`backend/app/ingestion/service.py` — the *only* DB-touching unit here.

- For each draft: look up by `(source, external_job_id)`. Existing → bump
  `last_seen_at`, count `seen`. Otherwise insert a `Job`, count `created`.
- `IntegrityError` on insert (concurrent writer / in-run dup) → rollback the
  poisoned insert, re-read, count `seen` (idempotent identity).
- Commits on success; rolls back + re-raises on failure. Returns
  `IngestionResult(created, seen, skipped_no_id)`.

### 2.5 Storage — two tables

**`jobs`** (`models/job.py`): `id`, `source`, `external_job_id` (nullable),
`title`, `company`, `location`, `first_seen_at`, `last_seen_at`, `updated_at`.
Identity = **partial unique index**
`uq_jobs_source_external_job_id (source, external_job_id) WHERE
external_job_id IS NOT NULL` (PBI 3), plus `ix_jobs_last_seen_at`.

**`crawl_runs`** (`models/crawl_run.py`, migration `0004`):
`status ∈ {running, succeeded, failed, skipped_locked}`, `trigger`,
`started_at` / `finished_at`, counters, `error`.

## 3. Read path: serving (PBIs 1, 4, 5)

### 3.1 FastAPI

`backend/app/main.py`, `backend/app/api/routes/jobs.py`

| Method | Path | Notes |
| --- | --- | --- |
| GET | `/health` | liveness |
| GET | `/jobs` | `limit` (1–100, default 50), `offset`, filters `source`, `company`, `location` (exact), `q` (`title ILIKE %q%`); returns `{items, total}` |
| GET | `/jobs/{id}` | detail or 404 |

Reads through `JobRepository` (`repositories/job.py`) on a `get_db()` session;
responses validated into shared `JobResponse` / `JobListResponse`
(`shared/jobsearch_shared/schemas.py`). CORS allows `http://localhost:5173`.

### 3.2 React SPA

`frontend/src`

- `JobsPage` — browse / filter / paginate via URL params.
- `JobDetailPage` — single job.
- `PbiTrackerPage` — renders the roadmap from `pbis.ts`.
- `api.ts` — typed fetch wrapper; `types.ts` — shared shapes.

## 4. What's deliberately not here yet (PBI 7+ hooks already planted)

- **Retry / backoff** — `RETRY_TIMES=0` explicitly leaves it to PBI 7.
- **Disappeared-job detection** — `last_seen_at` is bumped; PBI 8 will key
  "disappeared" off *observed successful runs*, never wall-clock days (hence the
  `crawl_runs` record and the "missed runs tolerated, not backfilled" rule).
- **Observability** — a run whose process never launched isn't recorded (only in
  the cron log); PBI 9 closes that.
- **Search** — `q` is a simple `ILIKE`; FTS → embeddings (pgvector already in the
  DB image) → hybrid ranking is Stage 3.
- **Location extraction** is the current gate: a client-rendered Tokyo listing
  yields 0 items because the spider's location text extraction finds no term.

## 5. Mental model

cron → `IngestRun` (lock + run record) → Scrapy crawl (rate-limited,
scope-guarded) → normalized `JobDraft`s → idempotent upsert into `jobs` on
`(source, external_job_id)` → FastAPI reads `/jobs` → React dashboard.

Correctness rests on three invariants:

1. **Advisory lock** — no overlapping crawls.
2. **Partial unique index** — no duplicate identities.
3. **Policy guard** — the crawl cannot widen its scope.
