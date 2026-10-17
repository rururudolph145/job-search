# PBI 4 — Query Routes: Design Spec

> Status: draft for review
> Date: 2026-10-17
> Depends on: PBI 1 (jobs schema + `JobRepository`), PBI 3 (dedup key + normalization)
> Blocks: PBI 5 (jobs dashboard page), PBI 10 (full-text search — consumes `q`'s slot)

## 1. Purpose

Expose the ingested `jobs` table over HTTP so a client can list, filter, and read
individual jobs. PBI 1 built the table and repository. PBI 2 filled it. PBI 3 gave
it a unique identity. PBI 4 is the first time any of that is readable by anything
other than a test — it is the query surface PBI 5's dashboard renders.

**Scope, in one line:** three read-only HTTP endpoints (`GET /jobs`,
`GET /jobs/{job_id}`) plus a count envelope, backed by the existing
`JobRepository`, with no schema change and no write path.

This is a **read-model PBI**. It ships endpoints and one new contract, and it does
**not** touch the ingestion pipeline.

## 2. Why read-only, and why now

PBI 4 is deliberately the narrowest slice that makes the data useful. PBI 5 needs
a stable query surface to build the dashboard against; nothing here invents new
data. The one non-obvious choice — a count envelope on the list — exists so the
dashboard can render pagination (`total` vs `offset`+`limit`) without a second
round-trip or a `COUNT(*)` of its own. The envelope is the smallest contract that
makes "how many pages" answerable.

## 3. Scope decisions (locked during design)

| Decision | Choice |
|---|---|
| Endpoints | **Two routes, three handlers.** `GET /jobs` (list + filters) and `GET /jobs/{job_id}` (detail). No `POST`/`PUT`/`DELETE` — ingestion owns writes. |
| Filter fields | **`source`, `company`, `location` (exact) + `q` (title substring).** Only fields that exist on `jobs` are filterable. No salary/date/remote — those columns do not exist yet. |
| `q` semantics | **Case-insensitive title substring (`ILIKE`).** Cheap today, and PBI 10 explicitly replaces it with real full-text search; `q` is not built out further to avoid pre-empting that work. |
| List shape | **Envelope:** `{ items: JobResponse[], total: int }`. |
| Pagination | `limit` (default 50, `ge=1 le=100`) and `offset` (default 0), ordered by `id`. |
| Repository growth | **`list()` gains filter args; `count()` is new.** Filter logic lives in the data layer so routes stay thin — matching the current `routes`/`repositories` split. |
| New columns | **None.** No `description`, `salary`, `date`, or `remote`. |
| Write path | **Untouched.** |

## 4. Components

### 4.1 Contract — `shared/jobsearch_shared/schemas.py`

`JobResponse` already exists and already carries every column in `jobs` (PBI 3 §4.4
confirmed it is consumed as-is). One **new** model:

```python
class JobListResponse(BaseModel):
    items: list[JobResponse]
    total: int
```

Re-exported through `backend/app/schemas/__init__.py` alongside `JobResponse`, so
the backend imports from `app.schemas` without a direct shared-package path in
application code (the convention the `__init__.py` docstring documents).

### 4.2 Repository — `backend/app/repositories/job.py`

- `list(...)` gains keyword args `source`, `company`, `location`, `q` (each
  optional). They add `WHERE` clauses to the existing `select(Job).order_by(Job.id)`
  before `.limit().offset()`:
  - `source` / `company` / `location` → exact `==` match.
  - `q` → `Job.title.ilike(f"%{q}%")` (case-insensitive substring).
- `count(...)` is new: same optional filters, returns
  `session.scalar(select(func.count()).select_from(Job)) or 0`.

Filter construction is factored into a private `_apply_filters` helper so `list`
and `count` cannot drift apart — the two must always agree on what "the matching
set" is, or `total` will contradict the returned page.

**No change** to `get`, `add`, or `find_by_external_id`.

### 4.3 Routes — `backend/app/api/routes/jobs.py` (new)

`APIRouter(prefix="/jobs", tags=["jobs"])`, mirroring `health.py`'s shape but adding
the session dependency `Depends(get_session)` from `app.db.engine`. Registered via
`app.include_router(jobs.router)` in `main.py`.

- `GET /jobs` → `JobListResponse`. Injects `Session` and `JobRepository` as FastAPI
  dependencies, plus the query params above. Calls `repo.list(...)` and
  `repo.count(...)` and wraps them in the envelope.
- `GET /jobs/{job_id}` → `JobResponse`. `repo.get(session, job_id)`; raises
  `HTTPException(404, "Job not found")` when `None`.

`JobRepository` is a zero-dependency plain class (not itself an ORM session), so
FastAPI dependency injection is used directly rather than a singleton — the lightest
wiring consistent with how `health` is registered and how the repo is unit-tested.

## 5. API surface

| Method | Path | Query params | Returns |
|---|---|---|---|
| GET | `/jobs` | `limit` (1–100, default 50), `offset` (≥0, default 0), `source`, `company`, `location`, `q` | `200` `JobListResponse` |
| GET | `/jobs/{job_id}` | — | `200` `JobResponse` or `404` |

`limit`/`offset` are bounded by FastAPI `Query` constraints (`ge`/`le`), so a bad
value is a clean `422` validation error rather than a SQL error.

## 6. Testing

Conventions match the repo: standalone modules, no `conftest.py`, SQLite `:memory:`
for unit tests, `monkeypatch.setattr(engine_mod, "engine", ...)` to bind the
session. Route tests use `TestClient(app)` as `test_routes_health.py` does — though,
because endpoints use `Depends(get_session)`, the module-level `engine` must be
monkeypatched to a SQLite engine before requests fire (the same monkeypatch pattern
`test_job_repository.py` uses).

| File | Covers |
|---|---|
| `shared/tests/test_schemas.py` *(extend)* | `JobListResponse` serializes `items` + `total`. |
| `backend/tests/test_job_repository.py` *(extend)* | `list` with each filter (`source`/`company`/`location` exact, `q` case-insensitive substring); `count` returns matching-total with and without filters; filtered `count` and filtered `list` agree. |
| `backend/tests/test_routes_jobs.py` *(new)* | `GET /jobs` default page + envelope shape; filter via `source`/`q`; `limit`/`offset` pagination; `limit=0` → `422`; `GET /jobs/{id}` returns a real row; unknown id → `404`. |

Two notes:

- **The `count`/`list` agreement test is the important one.** `total` must count the
  *same* rows `list` returns under identical filters, or the dashboard paginates
  wrong. One test drives both through the same filter set and asserts consistency.
- **Filter tests must seed `company`/`location`.** 711 real rows carry `NULL`
  `company` (PBI 3 §2), so exact-match filter coverage needs seeded non-null values.

## 7. Verification (end-to-end)

1. `make lint` — ruff check + format.
2. `make typecheck` — mypy strict over `backend/app` and `shared/jobsearch_shared`.
3. `make test` — pytest across `backend/tests` + `shared/tests`.
4. `make db-up && make migrate && make dev` — server boots with `/jobs` registered.
5. `curl http://localhost:8000/jobs?limit=5` → `200` envelope with `items` + `total`.
6. `curl http://localhost:8000/jobs?source=google_careers&q=software` → filtered,
   case-insensitive results; `total` consistent with an unfiltered count.
7. `curl http://localhost:8000/jobs/1` → a row; `curl .../999999999` → `404`.

## 8. Out of scope

- **Full-text search / relevance ranking** — PBI 10–12. `q` is a placeholder-level
  substring, deliberately minimal.
- **Embeddings / pgvector / hybrid ranking** — PBI 11–12.
- **New columns** (`description`, `salary`, `remote`, `date`) — later PBIs. PBI 4
  filters only existing columns; richer filters require the columns to exist.
- **Write endpoints** — ingestion owns writes (PBI 2, 6, 7).
- **Cross-ATS identity / matching** — deferred by PBI 3 §3.
- **Dashboard UI** — PBI 5 consumes these routes.
