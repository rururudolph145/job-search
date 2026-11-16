# PBI 2 — Source Ingestion: Design Spec

> Status: draft for review
> Date: 2026-10-14
> Depends on: PBI 1 (jobs schema + `JobRepository`)
> Blocks: PBI 6 (crawl scheduler), PBI 7 (failure recovery)

## 1. Purpose

Turn the throwaway Scrapy spike (`experiment_scrapy/`) into a real, tested
ingestion layer that populates the `jobs` table from a permitted feed. PBI 2's
job is to fetch listings and persist them faithfully — nothing more. Identity,
scheduling, and resilience belong to later PBIs and are explicitly out of scope
here (§9).

**Scope, in one line:** scrape Google Careers politely, for Tokyo software
engineering jobs only, and write what it finds into `jobs`.

## 2. Scope decisions (locked during design)

| Decision | Choice |
|---|---|
| Compliance posture | Google Careers sitemap only, exactly as the spike documents it. No other sources in this PBI. |
| Role filter | `software-engineer` URL-slug match (unchanged from spike). |
| Location filter | **Tokyo-metro terms only** — narrowed from the spike's Japan-wide city list. Non-matching pages yield nothing. |
| Trigger (MVP) | One-shot CLI: `python -m app.ingest` / `make ingest`. No scheduler (PBI 6). |
| Code location | Real module in `backend/app/ingestion/`; `experiment_scrapy/` is retired. |
| Persistence shape | Spider yields plain dicts; `IngestionService` maps → `Job` and writes via `JobRepository`. |
| Re-run behaviour | Insert, but use `JobRepository.find_by_external_id` to skip already-known listings (bump `last_seen_at` instead of inserting a duplicate). |
| Scrapy dependency | Added to `backend/pyproject.toml` as a normal dependency. Accepted cost: heavier backend install. |
| `external_job_id` | Parsed from the result URL path with a regex (`^(\d+)-`). |
| `company` | Best-effort extraction; **often `None`** (nullable schema already allows it). |

### Compliance note (carried forward from the spike)

The permitted feed is `https://careers.google.com/jobs/sitemap` — a publicly
exposed XML sitemap not covered by any `robots.txt` disallow. Job *detail pages*
redirect to `www.google.com/about/careers/applications/jobs/results/...`, a path
under Google's `robots.txt` `Disallow` prefix. The spike documents this as a gray
area for low-volume personal use, and the user has directed PBI 2 to treat the
spike's scope as authoritative. The paginated search/list URL (the primary
disallowed page) is **never** fetched. Politeness, rate limits, and robots-policy
enforcement are PBI 6's concern; PBI 2 stays minimal (`DOWNLOAD_DELAY`,
`AUTOTHROTTLE` left at Scrapy defaults / set via settings).

## 3. Architecture

```
CLI (`python -m app.ingest` / `make ingest`)
    └─> IngestionService(source, session_factory).run()
            ├─> source.fetch()  ──> Iterator[JobDraft]      (pure data)
            │      └─ GoogleCareersSource wraps the Scrapy crawl
            │             └─ GoogleCareersSpider yields dicts
            └─> for each JobDraft:
                    existing = JobRepository.find_by_external_id(
                        session, source=source.name, external_job_id=draft.external_job_id)
                    if existing:  existing.last_seen_at = now()
                    else:         JobRepository.add(session, <Job from draft>)
                commit once at end of run
```

Three units, each independently testable:

| Unit | File | Depends on | Tested by |
|---|---|---|---|
| `GoogleCareersSpider` | `backend/app/ingestion/spiders/google_careers.py` | Scrapy only | feed synthetic responses; assert yielded dicts — no DB, no network |
| `GoogleCareersSource` | `backend/app/ingestion/sources/google_careers.py` | Scrapy crawl runner | inject a fake crawl; assert `JobDraft`s |
| `IngestionService` | `backend/app/ingestion/service.py` | `JobRepository` + a `Session` factory | SQLite `:memory:` — no Scrapy, no network |

Package layout:

```
backend/app/ingestion/
    __init__.py                     # exports IngestionService, IngestionResult
    drafts.py                       # JobDraft
    service.py                      # IngestionService, IngestionResult
    sources/
        __init__.py                 # exports JobSource protocol, GoogleCareersSource
        base.py                     # JobSource Protocol
        google_careers.py           # GoogleCareersSource
    spiders/
        __init__.py
        google_careers.py           # GoogleCareersSpider
backend/app/ingest.py               # CLI entrypoint (`python -m app.ingest`)
```

## 4. Components

### 4.1 `JobDraft` — `backend/app/ingestion/drafts.py`

A frozen dataclass carrying exactly the fields a *source* can know. The service
owns `source` and the timestamps; sources never set those.

```python
@dataclass(frozen=True, slots=True)
class JobDraft:
    external_job_id: str  # required — a draft without one is never constructed
    title: str
    company: str | None
    location: str | None
    url: str
```

Frozen + slots because it is a value crossing the source→service boundary;
nothing should mutate it. Raw Scrapy dicts are validated into this at the source
boundary, so the service never handles a bare dict.

`external_job_id` is **required**: a yielded page with no parseable id is not
turned into a `JobDraft` at all — the source counts it as `skipped_no_id` and
skips it (see §4.4). This keeps the invariant "every `JobDraft` has an id the
service can dedup on" true at the type level.

### 4.2 `JobSource` protocol — `backend/app/ingestion/sources/base.py`

```python
class JobSource(Protocol):
    name: str  # e.g. "google_careers"
    def fetch(self) -> Iterator[JobDraft]: ...
```

The seam that lets PBI 6 add a second source without touching the service. `name`
is the `jobs.source` slug written by the service.

### 4.3 `GoogleCareersSpider` — `backend/app/ingestion/spiders/google_careers.py`

The spike promoted into the backend package and tightened:

- `start_urls = ["https://careers.google.com/jobs/sitemap"]`; parse `<loc>` by
  `local-name()` (the sitemap uses a default XML namespace).
- Filter URLs to `software-engineer` slugs (`ROLE_PATTERN`, unchanged).
- Per detail page, yield:

  | Field | Source |
  |---|---|
  | `title` | `og:title`, falling back to `<title>`, else `""` |
  | `url` | the result URL from the sitemap |
  | `location` | first **Tokyo-metro** term found in rendered body text |
  | `external_job_id` | regex `^(\d+)-` on the URL slug, e.g. `/jobs/results/83683003800134342-software-engineering-manager/` → `83683003800134342`. If no id parses, the field is `""` and the **source** drops the item (counts `skipped_no_id`) — see §4.4. |
  | `company` | best-effort heuristic (see below); may be `None` |

- **Tokyo-only location filter.** Replace the spike's Japan-wide list with
  Tokyo-metro terms: `Tokyo`, `Shinjuku`, `Minato`, `Chiyoda`, `Shibuya`,
  `Shibaura`, `Roppongi`, `Meguro`, `Setagaya`. A page matching none of these
  yields **nothing** (it is filtered out, not stored with a null location).

- **`company` extraction is best-effort.** Google Careers pages name the employer
  but expose no clean structured field (the spike's honest limitation). Attempt a
  heuristic from `og:site_name` / known title patterns; otherwise leave `None`.
  This is acceptable because `jobs.company` is nullable by schema.

### 4.4 `GoogleCareersSource` — `backend/app/ingestion/sources/google_careers.py`

Implements `JobSource`. Wraps a Scrapy `CrawlerProcess`/`CrawlerRunner` run and
converts each yielded dict → `JobDraft`. Dict → `JobDraft` conversion (and thus
validation) lives here, at the source boundary. `name = "google_careers"`.

A yielded dict whose `external_job_id` is missing or unparseable is **not**
converted to a `JobDraft` — it is counted as `skipped_no_id` and dropped. The
source therefore needs to report that count upward; `fetch()` is a generator that
populates a mutable counter passed in at construction (or the source exposes a
`skipped_no_id` attribute the service reads after iterating). This is the only
piece of per-source bookkeeping the service consumes besides the drafts.

The crawl must be injectable so tests can substitute a fake that yields canned
dicts without touching the network — e.g. a `crawl_runner`/`_run_crawl` seam the
source calls, which tests replace.

### 4.5 `IngestionService` — `backend/app/ingestion/service.py`

The only unit that talks to the database.

```python
@dataclass(frozen=True)
class IngestionResult:
    created: int
    seen: int
    skipped_no_id: int

class IngestionService:
    def __init__(
        self,
        source: JobSource,
        session_factory: Callable[[], Session],
    ) -> None: ...

    def run(self) -> IngestionResult: ...
```

`run()` opens one session from the factory and iterates `source.fetch()`. Every
item yielded is already a `JobDraft` with a non-empty `external_job_id` (the
source guarantees it — §4.4), so the service does no id-skipping itself. For each
draft it looks up `JobRepository.find_by_external_id(session, source=source.name,
external_job_id=draft.external_job_id)`:

- **found** → set `last_seen_at = now()`, increment `seen`.
- **not found** → build a `Job` with `source = source.name`, `external_job_id`,
  `title`, `company`, `location`, `first_seen_at = last_seen_at = now()`, and
  `JobRepository.add(session, job)`; increment `created`.

After the iteration completes, the service reads `source.skipped_no_id` and
carries it into the result. It then commits once, and returns the
`IngestionResult(created=..., seen=..., skipped_no_id=...)`.

The `now()` used for timestamps is a single UTC-aware value captured at the start
of the run, not per-row, so a run's rows share a timestamp. The clock is
injectable (a `now_provider: Callable[[], datetime]` defaulting to
`datetime.now(timezone.utc)`) so tests can assert deterministically.

### 4.6 CLI — `backend/app/ingest.py`

Entrypoint run as `python -m app.ingest` (and exposed via `make ingest`). It:

1. Builds a real session factory from `app.db.engine` (`make_engine` → `Session`).
2. Constructs `GoogleCareersSource`.
3. Runs `IngestionService(...).run()`.
4. Prints the `IngestionResult` (created / seen / skipped_no_id) and exits 0.

`--limit N` is supported to stop after N items (useful for a smoke run); no other
arguments in this PBI. The source is constructed behind a small seam so the CLI
is testable without network access.

## 5. Error handling

| Condition | Behaviour |
|---|---|
| Detail-page fetch fails (403/404/timeout) | Logged and skipped via Scrapy's `errback`; crawl continues. No retry — PBI 7. |
| Page yields no `external_job_id` | Row dropped, counted in `skipped_no_id`. Not an error. |
| Sitemap unreachable | Crawl yields nothing; `run()` returns a zero-count result; CLI logs a clear message and exits non-zero. |
| DB error at the end-of-run commit | Commit fails → nothing persisted; exception propagates to the CLI. Partial-batch semantics are PBI 7's concern. |

Distinguishing a *failed fetch* from a *successful empty response* is explicitly
PBI 8's job; PBI 2 only needs the CLI to surface "sitemap unreachable" vs "no
Tokyo SWE jobs found" clearly in its output.

**Known limitation (accepted):** the single end-of-run commit means a crash
mid-crawl loses the whole batch. Per-run batching is PBI 7's idempotency work.

## 6. Dependencies & configuration

- Add `scrapy` to `backend/pyproject.toml` `[project].dependencies`.
- Add a `make ingest` target alongside `make dev` / `make migrate`.
- No new environment variables required. The sitemap URL is a module constant
  (matching the spike); making it configurable is PBI 6's `job_sources` concern.

## 7. Testing

Match the existing conventions: standalone test modules, no `conftest.py`, SQLite
`:memory:` for unit tests, `monkeypatch.setattr(engine_mod, "engine", ...)` where
the engine singleton is involved.

- **`backend/tests/test_google_careers_spider.py`** — drive the spider's parse
  methods with synthetic `HtmlResponse`/`TextResponse` fixtures (built in memory,
  no network):
  - a Tokyo SWE job → yielded dict has `title`, `url`, `location="Tokyo"`, and a
    correctly parsed `external_job_id`.
  - a non-Tokyo SWE job → yields nothing.
  - a non-`software-engineer` slug → not requested / yields nothing.
  - a URL with no leading numeric id → the spider still yields a dict, but the
    source drops it and counts it as `skipped_no_id`.
- **`backend/tests/test_ingestion_service.py`** — a `FakeSource` yielding canned
  `JobDraft`s and exposing a settable `skipped_no_id`; SQLite `:memory:` session;
  tables created via `Base.metadata.create_all`; injected `now_provider`:
  - new draft → one row; `source` set to the source name;
    `first_seen_at == last_seen_at`; `created == 1`.
  - same draft twice in one run, and across two runs → still one row;
    `last_seen_at` bumped; counts `created=1, seen=1`.
  - `FakeSource` with `skipped_no_id = 1` and no drafts → result reports
    `skipped_no_id == 1`, no row written.
  - empty source → all counts zero, no error.
- **`backend/tests/test_ingest_cli.py`** — invoke the CLI entrypoint with a fake
  source wired through the seam; assert it prints the result and exits 0. No
  network.
- **`@pytest.mark.integration` (network; skipped by default):** a real crawl with
  `CLOSESPIDER_ITEMCOUNT=1` asserting a non-empty result — mirrors PBI 1's
  Postgres-marked migration test.

## 8. Verification (end-to-end)

1. `make lint` — ruff check + format.
2. `make typecheck` — mypy strict over `backend/app` and `shared/jobsearch_shared`.
3. `make test` — pytest across `backend/tests` + `shared/tests`.
4. `make db-up && make migrate` — Postgres up and migrated.
5. `make ingest` — a real run against the live sitemap; confirm rows land in
   `jobs` via `docker compose exec` / `psql`.
6. Re-run `make ingest` — confirm no duplicate rows are inserted for known
   listings (only `last_seen_at` advances).
7. Retire `experiment_scrapy/` (delete the spike, or leave a one-line pointer to
   the promoted module).

## 9. Out of scope

- **Dedup / canonical job identity** — PBI 3. PBI 2 skips known
  `(source, external_job_id)` pairs only as a convenience, not as a dedup policy.
  The `(source, external_job_id)` index remains non-unique.
- **Scheduling, per-host rate limits, robots.txt/policy enforcement** — PBI 6.
- **Retry / exponential backoff / idempotent writes** — PBI 7.
- **"Disappeared job" detection** — PBI 8.
- **Sources other than Google Careers** — later PBIs.
- **`companies` / `job_sources` tables** — revisited at PBI 3.
- **`content_hash`, structured location, `description`/`requirements`** — PBI 3+.

## 10. Adjacent loose end

The tracker still shows **PBI 1 as `[ ]`** although the schema, migration,
repository, and contract are implemented and tested, and its spec/plan are
untracked in git. This is not PBI 2's work, but the PBI 2 line's checkbox will
be ticked in the same tracker file — worth resolving PBI 1's status first so the
file reflects reality.
