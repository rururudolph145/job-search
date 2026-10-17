# MVP Report — Stage 1 (PBIs 1–4)

**Date:** 2026-10-17
**Branch:** `pbi1-jobs-schema` (44 commits, 2026-10-12 → 2026-10-17)
**Scope:** Everything delivered from scaffolding through PBI 4 (query routes). PBI 5 (dashboard UI) is not started.

---

## 1. Where Stage 1 stands

```
Stage 1 — MVP
  [x] PBI 1  Jobs schema
  [x] PBI 2  Source ingestion
  [x] PBI 3  Normalization + dedup keys
  [x] PBI 4  Query routes
  [ ] PBI 5  Jobs dashboard page        <-- the only remaining MVP item
```

The backend half of the MVP is complete and verified against real Postgres. The
frontend currently ships only the PBI tracker page; the dashboard that consumes
`GET /jobs` is PBI 5.

---

## 2. What each PBI delivered

### Boilerplate (pre-PBI)

- `uv` workspace: `backend/` (FastAPI), `shared/` (Pydantic contracts), `frontend/` (Vite + React + TS).
- Postgres 16 + pgvector via Docker Compose; `psycopg` 3 driver chosen over `psycopg2` deliberately.
- Alembic wired with an empty baseline; health route + CORS; ruff + mypy strict + pytest gates.
- PBI tracker stored twice (`implementation_checklist/pbi_tracker.md` and `frontend/src/pages/pbis.ts`) with a test pinning them together so they cannot drift silently.

### PBI 1 — Jobs schema

Single `jobs` table (the tracker originally implied three tables; `companies` and
`job_sources` were cut under a "remove what's not necessary for MVP" directive).
Columns were admitted only if something writes them in PBI 1–2. `JobRepository`
with four primitives (`get`, `list`, `add`, `find_by_external_id`) and no business
logic. `JobResponse` shared contract established the ORM↔contract boundary.

**Key deferral:** the `(source, external_job_id)` index was created **non-unique** —
"encoding a uniqueness rule now would pre-empt PBI 3's identity decision."

### PBI 2 — Source ingestion

Google Careers sitemap crawl scoped to Tokyo-metro software engineering roles.
Three layers: `GoogleCareersSpider` (Scrapy) → `GoogleCareersSource` (`JobSource`
protocol, injectable runner) → `IngestionService` (only DB caller). A frozen
`JobDraft` is constructed at the source boundary so the service never handles a
bare dict. One commit per run; single UTC timestamp captured at run start.

`company` extraction is best-effort and documented as "often `None`".

**Accepted risk, stated at design time:** a crash mid-crawl loses the whole batch.

### PBI 3 — Normalization + dedup keys

The most significant design change in the project so far. The original plan was a
`content_hash` over `(title, company, location)`. Live-DB inspection showed
`company` was NULL on all 711 rows and that 26 groups of `(title, company, location)`
were distinct requisitions. The spec's conclusion: the hash "would **not
deduplicate. It would delete.**"

Replaced with:

- **Partial unique index** `uq_jobs_source_external_job_id ON (source, external_job_id) WHERE external_job_id IS NOT NULL` — partial rather than relying on Postgres's implicit NULL behavior, and scoped by source because provider ids are only unique within a provider.
- **Pure normalization functions** applied at one choke point (the `JobDraft` boundary): lowercase `source`, strip `external_job_id`, NFKC + whitespace collapse on display fields.
- **`UniqueViolation` handled explicitly** in the service so it is correct under a concurrent writer, not merely usually-correct.
- **Existing rows: constrain only** — no backfill, pinned by a test asserting the known-dirty row is left alone.

**Known, documented gap:** sources that supply no `external_job_id` produce no
drafts at all, so their jobs are never ingested. Unreachable by construction; not
fixable within PBI 3.

### PBI 4 — Query routes

Two read-only routes, no schema change, no write path.

| Route | Behavior |
|---|---|
| `GET /jobs` | Envelope `{items, total}`; filters `source`/`company`/`location` (exact) and `q` (case-insensitive title substring); `limit` 1–100 (default 50), `offset` ≥ 0; ordered by `id` |
| `GET /jobs/{job_id}` | `200` with the job; `404 {"detail": "Job not found"}` when absent |

Filter logic lives in the repository (`_apply_filters` shared by `list` and
`count` so pagination cannot lie); routes stay thin. `q` is deliberately a
placeholder that PBI 10 replaces with real full-text search.

Also fixed a latent defect uncovered here: `get_session` was a `@contextmanager`
and could not be used with `Depends` — every request 500'd. Added `get_db`, a
plain generator sharing the same engine and pool.

---

## 3. Verification state

### Automated gates (run 2026-10-17)

| Gate | Command | Result |
|---|---|---|
| Tests | `make test` | **64 passed**, 4 deselected (network), 1 warning |
| Lint | `make lint` | Clean (ruff check + format, 59 files) |
| Types | `make typecheck` | Clean, mypy strict, 29 source files |

Test distribution (76 test functions total, 4 network-gated):

| Module | Tests | Covers |
|---|---:|---|
| `test_job_repository.py` | 12 | PBI 1 + 3 + 4 data access |
| `test_routes_jobs.py` | 8 | PBI 4 routes |
| `test_ingestion_service.py` | 7 | PBI 2/3 service |
| `test_normalize.py` | 7 | PBI 3 normalization |
| `test_google_careers_spider.py` | 6 | PBI 2 spider |
| `test_google_careers_source.py` | 5 | PBI 2 source |
| `test_engine.py` | 4 | Engine + `get_db` dependency |
| `test_job_model.py` | 4 | PBI 1/3 schema |
| `shared/tests/test_job_response.py` | 4 | Contracts |
| `test_ingest_cli.py` | 3 | PBI 2 CLI |
| `test_migration_0003.py` | 3 | PBI 3 Postgres-gated |
| `test_config.py` / `test_cors.py` / `test_routes_health.py` / `shared/test_schemas.py` | 2/1/1/2 | Boilerplate |
| `test_ingest_integration.py` | 1 | Live crawl (opt-in) |

Codebases: ~785 lines of application code (`backend/app` + `shared`), ~1,212
lines of tests.

Not run in this report: `make test-integration` (live crawl, opt-in) and the
frontend Vitest suite.

---

## 4. Smoke tests

Three smoke passes were run against real Postgres. Results below are transcribed
from actual command output, not restated from expectations.

### 4.1 PBI 4 smoke — seeded data (5 rows)

Run to exercise filters on fields that real data does not populate (`company`).

| Check | Result |
|---|---|
| `GET /jobs?limit=5` | `200`, well-formed envelope, ordered by id |
| `source=google_careers&q=software` | `200`, 2 matches |
| `company=Google&location=Tokyo` | `200`, 2 matches (excluded Osaka row) |
| `q=DESIGNER` (uppercase) | `200`, 1 match — case-insensitivity holds on Postgres |
| `source=nonexistent` | `200`, `{"items": [], "total": 0}` |
| `limit=2&offset=3` | `200`, last 2 of 5 |
| `limit=0` / `limit=101` / `offset=-1` | `422` with Pydantic bodies |
| `GET /jobs/22` | `200` with the job |
| `GET /jobs/999999999` | `404 {"detail": "Job not found"}` |
| `GET /jobs/not-an-int` | `422` |
| `q=software&limit=1` | `total=3`, 1 item — filtered total, not table total |

Server log: 0 tracebacks; 15 requests (10×200, 1×404, 4×422).

Seeded rows were deleted afterwards.

### 4.2 Data-layer verification — real ingestion

The database was found **empty** (0 rows) despite PBI 3's spec describing a
711-row dataset. A real `make ingest` was run to verify the PBI 2/3 path still
works end to end:

```
ingestion complete: created=750 seen=0 skipped_no_id=0
```

Verified against the live data:

| Claim from PBI 3 spec | Observed 2026-10-17 |
|---|---|
| `company` is NULL on every row | **750 / 750 NULL** ✓ |
| Single source | `google_careers` only ✓ |
| `location` populated | 750 / 750 non-NULL ✓ |
| Dirty title at `id=431` left un-normalized | `Staff Software Engineer, Kernel Virtualization` ✓ |
| Partial unique index exists with predicate | ✓ `WHERE (external_job_id IS NOT NULL)` |
| Migration state | `0003` ✓ |

### 4.3 PBI 4 smoke — real data (750 rows)

| Check | Result |
|---|---|
| `GET /jobs` | `200`, `total=750`, 50 items (default page), first id 23 |
| `limit=5` / `limit=100` | `200`, 5 / 100 items, `total=750` |
| `limit=5&offset=745` | `200`, last 5 of 750 — offset pagination correct at the boundary |
| `q=manager` | `200`, `total=91` |
| `q=machine learning` | `200`, `total=9` |
| `q=SOFTWARE` | `200`, `total=750` — see finding 5.1 |
| `q=SOFTKWARE` | `200`, `total=0` — no fuzzy matching (by design) |
| `source=google_careers` | `200`, `total=750` |
| `source=linkedin` | `200`, `total=0` — no LinkedIn source exists yet |
| `location=Tokyo` | `200`, `total=750` — filter works, uninformative on this data |
| `company=Google` | `200`, `total=0` — see finding 5.2 |
| `limit=0` / `limit=101` / `offset=-1` | `422` / `422` / `422` |
| `GET /jobs/23` | `200` with the job |
| `GET /jobs/999999999` | `404 {"detail": "Job not found"}` |
| Unfiltered `total` vs table | 750 = 750 — count/list agree |

Server log: 0 tracebacks; 21 requests (17×200, 1×404, 3×422).

---

## 5. Findings

### 5.1 `q=software` matches every row (cosmetic today, blocking tomorrow)

All 750 titles contain "software" — a direct consequence of PBI 2's scope, which
ingests only software engineering roles. Verified:
`count(*) FILTER (WHERE title ILIKE '%software%')` = 750 of 750.

`q` is correct; the corpus is homogeneous. This is harmless now but means `q`
cannot be meaningfully exercised until either the source scope widens or PBI 10
replaces it with ranked full-text search.

### 5.2 `company` and `location` filters are near-useless on real data

- `company` is NULL on 100% of rows, so `?company=Google` returns 0. Every actual
  employer is Google; the field carries no information.
- `location` works but every row is Tokyo, so it cannot discriminate.

Both filters are correctly implemented and tested (against seeded rows), but on
current data they are decorative. They become useful when a second source lands
or when PBI 3's deferred company work is picked up.

### 5.3 The live database had been emptied outside the code

The `jobs` table held 0 rows while the id sequence was at 22, and the volume
persists across `db-down`/`db-up`. No code path truncates the table. The PBI 3
spec's 711-row findings were made against data that is no longer present — the
claims still reproduce (section 4.2), but the original 711 rows are gone. If
those rows held anything worth keeping, they were lost before this report.

### 5.4 `make ingest --limit N` is a no-op

`run_ingestion(limit)` accepts the argument and never passes it to
`IngestionService.run()`. The flag is advertised in `--help` and the docstring
("stop after N items (useful for a smoke run)") but has no effect. This is why
the data-layer verification in 4.2 inserted all 750 rows rather than a capped
batch. Pre-existing, out of scope for PBI 4, worth a ticket.

### 5.5 The PBI 4 plan had two defects that code review caught

Both are recorded in the plan file:

1. Test fixtures seeded multiple rows with the default `external_job_id="123"`,
   colliding with the unique index. The first RED gate failed for the wrong
   reason (IntegrityError, not missing feature) and had to be fixed before it
   was honest.
2. The plan wired `Depends(get_session)`, which cannot work — `get_session` is a
   `@contextmanager`, and FastAPI wraps it a second time, so every request
   failed with `TypeError: '_GeneratorContextManager' object is not an iterator`.
   Discovered only because the test actually ran the route.

---

## 6. Deferred work, consolidated

| Item | Deferred to | Stated in |
|---|---|---|
| Full-text search replacing `q` | PBI 10 | PBI 4 §8 |
| `content_hash` over job bodies | First body-scraping PBI | PBI 3 |
| Companies table / company normalization | Unassigned (was "revisit at PBI 3") | PBI 1 §11, PBI 3 §9 |
| Cross-ATS entity resolution | Needs a second source + accuracy eval | PBI 3 §9 |
| Id-less sources never ingested | Unfixable in PBI 3; known gap | PBI 3 |
| Re-normalizing legacy rows | Separate task if ever wanted | PBI 3 §9 |
| Retry / backoff / idempotent writes | PBI 7 | PBI 2 §9 |
| Disappeared-job detection | PBI 8 | PBI 3 |
| Scheduler / rate limits / robots enforcement | PBI 6 | PBI 2 §9 |
| Dashboard UI | PBI 5 | PBI 4 |

---

## 7. Process observations

- **TDD was followed throughout**, including for the `get_db` bug. The Task 4
  pinning tests passed immediately (as the plan anticipated), so the four
  behaviours were additionally **mutation-tested** — each mutation (drop count
  filters, remove `le=100`, return `{}` for an empty list, make `q` exact) failed
  exactly the intended test. A passing test that has never been seen to fail
  proves less than one that has.
- **The strongest design decision in the sequence was a reversal.** PBI 3's
  switch from `content_hash` to a partial unique index was driven by querying the
  live database rather than reasoning from the schema. The evidence said the
  proposed design would have deleted 26 real job postings.
- **Plan defects surface only when executed.** Two of PBI 4's four defects were
  in the plan document, not the implementation; both were caught by running the
  tests rather than reviewing the code.
- **The PBI 1 tracker checkbox was left `[ ]`** and flagged as an unresolved
  loose end in both PBI 2 §10 and PBI 3 §10. It is `[x]` now, but the recurrence
  suggests the tracker update should be a step in the plan template, not a
  follow-up note.
