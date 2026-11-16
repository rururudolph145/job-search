# PBI 6 — Crawl Scheduler: Design Spec

> Status: draft for review
> Date: 2026-10-27
> Depends on: PBI 2 (source ingestion), PBI 3 (dedup key)
> Blocks: PBI 8 ("disappeared job" detection — assumes a crawl cadence and an
> observed-run record), PBI 9 (observability — consumes the per-run result and
> Scrapy stats this PBI makes explicit)

## 1. Purpose

Today the crawler runs when a human types `make ingest`. Nothing schedules it,
nothing limits how fast it hits Google, and the compliance posture that makes the
crawl acceptable exists only as a paragraph in PBI 2's spec. PBI 6 turns three
implicit properties into three explicit, testable ones:

1. **Cadence** — the crawl runs on a timer, unattended, with a record of every
   attempt that reached the application.
2. **Politeness** — the crawl's request rate is set deliberately in code, not
   inherited from Scrapy's defaults.
3. **Compliance** — the crawl scope PBI 2 established is ratified and made
   executable: the spider can only ever request URLs the policy permits, and a
   test (and a runtime guard) proves it.

**Scope, in one line:** add a cron-driven run record and advisory lock to the
existing ingestion path, pin Scrapy's politeness settings in a real settings
module, and add a policy guard that raises if the crawl reaches outside its
permitted scope.

This is a **back-end ingestion PBI**. No schema change to `jobs`, no new API
route, no frontend change. One new table (`crawl_runs`), one new dependency
(`croniter`), and three new modules in the ingestion package
(`scrapy_settings.py`, `middleware.py`, `run.py`) plus `policy.py` and
`locking.py`.

## 2. Why this shape

Three choices carry the PBI, and each rejects a heavier alternative:

- **Cron on the host, not a scheduler service.** The user runs this for
  themselves; a `crontab` line that shells out to the existing
  `python -m app.ingest` is a real scheduler with zero infrastructure. The same
  command line copies verbatim into a GitHub Actions `schedule:` step if the
  cadence ever needs to leave the laptop. APScheduler-in-process was rejected: the
  crawl is synchronous and Twisted-driven (`sources/google_careers.py`,
  `process.start()`), so scheduling it inside the FastAPI process would stall
  every `/jobs` request for the crawl's duration — and a crawler crash would take
  the API down with it. Argo CD / Kubernetes CronWorkflow was rejected as orders
  of magnitude more operational surface than a personal tool needs.
- **A run record in the database, not a log file.** Cron's output goes to a log
  file the user has to remember to read. A `crawl_runs` row is the same fact in a
  place PBI 9 can query and PBI 8 can consume. It also answers "when did we last
  successfully crawl?" without grepping.
- **Ratify PBI 2's robots scope; do not reopen it.** The detail pages sit under
  Google's `robots.txt` `Disallow` prefix; the sitemap-`<loc>`-only crawl scope
  is the user's standing decision, restated in §6.1. What PBI 6 adds is not a new
  policy but an executable statement of the existing one.

## 3. Scope decisions (locked during design)

| Decision | Choice |
|---|---|
| Scheduler | **cron on the host** (`crontab -e`), running `make ingest`. No `systemd` timer, no in-process scheduler, no queue/broker. |
| Cadence | **Daily**, at an off-:00 minute (`17 6 * * *` = 06:17 host-local). A starter cadence; the crawl is cheap to re-run and the schedule is one crontab line to change. |
| Overlap protection | **Postgres advisory lock** (`pg_try_advisory_lock`) held by `IngestRun` for the whole crawl; a concurrent run writes a `skipped_locked` row and exits non-zero with a distinct code. |
| Session model | **One session for lock, run row, and crawl.** `IngestionService.run()` gains an optional `session` parameter; `IngestRun` opens a single session and threads it through. |
| Run record | **New table `crawl_runs`** — one row per attempt, written by `IngestRun`, not by `IngestionService`. |
| Politeness config | **Pure settings module** (`ingestion/scrapy_settings.py`) returning a plain dict; `_make_process` consumes it. No `scrapy.cfg` (the app is not a Scrapy project). |
| Policy guard | **Separate Scrapy-importing module** (`ingestion/middleware.py`); registered by dotted path from the pure settings dict. |
| Robots enforcement | **`ROBOTSTXT_OBEY` explicitly `False`.** A policy guard test and a runtime middleware assert structural scope instead (§6.1, §6.3). |
| Retries | **`RETRY_TIMES = 0`** — retry/backoff is PBI 7 and must not stack here. |
| Per-host rate budgets | **A registry keyed by registrable host**, resolved per source. One host today; the shape is what matters. |
| `--limit` | **Removed.** It is parsed in `main()` today but never reaches the crawl (`IngestionService.run()` has no limit parameter). Deleting dead code is not scope creep; fixing it would be. |
| `--trigger` | **Added** (`cron` \| `manual`, default `manual`), threaded from `main()` → `IngestRun` → `crawl_runs.trigger`. The Makefile `ingest` target forwards it: `make ingest TRIGGER=cron`. |
| API process | **Untouched.** No import from `app.api` or `main.py` into ingestion, or vice versa. |
| Schema | **One new table, one Alembic revision.** `jobs` is unchanged. |
| New dependencies | **`croniter`** (validate the documented cadence in a test). No scheduler library. |
| Missed runs | **Tolerated, not backfilled.** PBI 8 must key "disappeared" off observed successful runs, not wall-clock days (§6.8). |

## 4. Constraints and anti-goals

**Constraints**

- `make test` must stay hermetic — no network, no live Postgres, no real cron.
  Every new unit is testable on in-memory SQLite.
- Mypy strict (`disallow_untyped_defs`, `no_implicit_optional`) over every new
  module. Every function — including Scrapy middleware methods — carries full
  annotations. New modules begin with `from __future__ import annotations`.
- Ruff E/W/F/I/C/B, double quotes.
- **SQLite timezone convention.** SQLite drops the offset from
  `DateTime(timezone=True)`. Tests comparing a stored timestamp to `FIXED_NOW`
  must compare against `FIXED_NOW.replace(tzinfo=None)`, exactly as
  `test_ingestion_service.py` does today.
- **Single clock source.** `IngestRun` takes one `now_provider`; the same captured
  `now` stamps the run row and is passed to `IngestionService`, so `started_at`,
  `finished_at`, and job timestamps are consistent across a run.
- The crawl must remain **one command** (`python -m app.ingest`). Cron, a manual
  run, and any future GitHub Actions step all invoke the same entrypoint — no
  divergent scripts.
- Migration and crawl must run against a **direct** Postgres connection when the
  DB eventually moves to a pooled provider; advisory locks and long transactions
  are pool-hostile. Locally this is a non-issue; it is recorded so the Neon move
  is a config change (§6.8).

**Anti-goals** (this PBI fails even if the code "works" if any of these happen)

- A scheduled run and a manual run crawl concurrently.
- `ROBOTSTXT_OBEY` left unset so a Scrapy upgrade that flips the default silently
  empties the crawl — a blocked request must never be indistinguishable from an
  empty feed.
- A crawler change that widens request scope (pagination, search API, a second
  page type) without a test failing.
- Scheduling landing inside the FastAPI process.
- A missed cron run being recorded as a *successful* crawl.
- `jobs` gaining columns or semantics in a PBI about when, not what, we crawl.

## 5. Architecture

```
host crontab ──> `make ingest TRIGGER=cron` ──> python -m app.ingest --trigger cron
                                                  │
                                                  ▼
                                              IngestRun.run()
                                                  │
          ┌───────────────────────────────────────┼───────────────────────────┐
          │ one Session (engine)                  │                           │
          ▼                                       ▼                           ▼
   ingestion_lock(session)              CrawlRunRepository          IngestionService(session=...)
   ├─ not held → record skipped_locked              │                           │
   │             commit → exit 2                     │                           ▼
   └─ held → repo.start() ──────────────────────────┘                    source.fetch()
              └─ svc.run(session)  ────────────────────────────────────►  spider + settings
              └─ repo.finish()                                                 └─ PolicyGuard
              └─ session.commit()                                                 (raises on
                                                                                   out-of-scope URL)
              on exception: rollback → repo.fail() → commit → exit 1

FastAPI (uvicorn app.main:app) ── reads `jobs` only — never imports app.ingestion.sources
```

**Units**

| Unit | File | Depends on | Tested by |
|---|---|---|---|
| `crawl_runs` model | `backend/app/models/crawl_run.py` | SQLAlchemy | SQLite `:memory:`; column/index assertions |
| `CrawlRunRepository` | `backend/app/repositories/crawl_run.py` | model | SQLite `:memory:` |
| `ingestion_lock` | `backend/app/ingestion/locking.py` | a `Session` | SQLite "always yields True" + opt-in Postgres test |
| `build_scrapy_settings` | `backend/app/ingestion/scrapy_settings.py` | pure (no Scrapy import) | pure-function tests |
| `PolicyGuardMiddleware` | `backend/app/ingestion/middleware.py` | Scrapy | middleware unit tests |
| `RateBudget` / `budget_for` | `backend/app/ingestion/policy.py` | pure | pure-function tests |
| `IngestRun` | `backend/app/ingestion/run.py` | lock, repo, `IngestionService` | SQLite `:memory:` with a fake source |
| `IngestionService` (changed) | `backend/app/ingestion/service.py` | optional `session` param | existing tests + new shared-session test |
| `GoogleCareersSource` (changed) | `backend/app/ingestion/sources/google_careers.py` | settings module | inject a fake crawl |
| spider (changed) | `backend/app/ingestion/spiders/google_careers.py` | policy guard | parsed-request tests |

The existing three-unit shape from PBI 2 (§3) is preserved. Everything new except
`IngestRun` is either pure or DB-only.

## 6. Components

### 6.1 Robots policy — ratified, not reopened

**This section restates PBI 2 §2's "Compliance note" and is a ratification, not a
new decision.** It is here so the policy has a citable home in the PBI that makes
it executable.

| Aspect | State |
|---|---|
| Permitted feed | `https://careers.google.com/jobs/sitemap` — a public XML sitemap, not disallowed. |
| Detail pages | Redirect to `www.google.com/about/careers/applications/jobs/results/…`, **under Google's `robots.txt` `Disallow` prefix.** |
| Standing decision | The user directed PBI 2 (and re-affirmed 2026-10-27) to treat the spike's scope as authoritative: **low-volume personal use, sitemap-`<loc>`-declared URLs only.** |
| Never fetched | The paginated search/list page (the primary disallowed page). No URL that is not a sitemap `<loc>` is ever requested. |
| Volume posture | Single-request-per-domain serial crawl with a real delay (§6.3) — "low-volume" is enforced, not asserted. |
| Reopening trigger | PBI 3 §2.1's named trigger: **the first PBI that scrapes job bodies** (or any change that adds pagination / a second page type). That PBI reopens this table; PBI 6 must not. |

**Why `ROBOTSTXT_OBEY` is set to `False` explicitly.** Verified against the
installed Scrapy: the default is currently `False`, so today omitting the key
would behave identically. It is nonetheless pinned to `False` in the settings dict
so that a future Scrapy release changing the default cannot silently empty the
crawl. The policy is enforced **structurally** (§6.3), not by an opt-out
middleware. If a future PBI reopens the scope, enabling `RobotsTxtMiddleware` is a
legitimate option *at that point*.

### 6.2 Rate budgets — `backend/app/ingestion/policy.py`

A pure module with no Scrapy import.

```python
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from urllib.parse import urlsplit


class UnconfiguredHostError(LookupError):
    """Raised when a host has no rate budget — a config bug, not a default."""


@dataclass(frozen=True, slots=True)
class RateBudget:
    """Politeness knobs for one registrable host."""

    download_delay: float
    concurrent_requests_per_domain: int
    autothrottle_target_concurrency: float
    autothrottle_max_delay: float


GOOGLE_BUDGET = RateBudget(
    download_delay=2.0,
    concurrent_requests_per_domain=1,
    autothrottle_target_concurrency=1.0,
    autothrottle_max_delay=30.0,
)

BUDGETS: Mapping[str, RateBudget] = {"google.com": GOOGLE_BUDGET}


def registrable_host(url: str) -> str:
    """Two-label suffix of the URL's host (``www.google.com`` → ``google.com``)."""


def budget_for(url: str) -> RateBudget:
    """Look up the host's budget; unknown hosts raise ``UnconfiguredHostError``."""
```

- `registrable_host` is deliberately two-label, not a public-suffix-list lookup.
  A PSL dependency is not justified for one vendor today; the docstring names PSL
  as the upgrade path if multi-label suffixes ever appear.
- Unknown-host failure is the point: a new source with no budget is a config bug,
  and it surfaces at first crawl rather than as permissive defaults.

### 6.3 Scrapy settings — `backend/app/ingestion/scrapy_settings.py`

A **pure** function returning a plain `dict[str, object]`; no Scrapy import, so it
is trivially testable.

```python
def build_scrapy_settings(
    *,
    verbose: bool = False,
    source_url: str = "https://careers.google.com/jobs/sitemap",
) -> dict[str, object]:
    """Politeness + collection pipeline for the google_careers crawl."""
```

Returns at minimum:

| Setting | Value | Why |
|---|---|---|
| `ITEM_PIPELINES` | `{"app.ingestion.sources.google_careers._CrawlItemsPipeline": 1}` | unchanged from PBI 2 |
| `SPIDER_MIDDLEWARES` | `{"app.ingestion.middleware.PolicyGuardMiddleware": 543}` | structural scope guard (§6.3.1) |
| `LOG_ENABLED` | `True` | Scrapy's default; kept explicit |
| `LOG_LEVEL` | `"INFO"` if verbose else `"DEBUG"`… see note | unchanged verbosity behaviour |
| `DOWNLOAD_DELAY` | `budget.download_delay` | explicit, not default |
| `RANDOMIZE_DOWNLOAD_DELAY` | `True` | jitter |
| `CONCURRENT_REQUESTS` | `1` | one request in flight, period |
| `CONCURRENT_REQUESTS_PER_DOMAIN` | `1` | serial per host |
| `AUTOTHROTTLE_ENABLED` | `True` | explicit |
| `AUTOTHROTTLE_TARGET_CONCURRENCY` | `1.0` | never faster than serial |
| `AUTOTHROTTLE_MAX_DELAY` | `30.0` | bounded backoff on throttling |
| `AUTOTHROTTLE_DEBUG` | `verbose` | surface waits for PBI 9 |
| `RETRY_TIMES` | **`0`** | retry belongs to PBI 7 |
| `ROBOTSTXT_OBEY` | **`False`** (explicit) | §6.1 |

**Verbosity note:** PBI 2's `_make_process` *disabled* logging entirely when not
verbose (`LOG_ENABLED = False`). Preserve that exactly: `LOG_ENABLED = verbose`
and `LOG_LEVEL = "INFO" if verbose else "DEBUG"` — the level is then irrelevant
when logging is off, but the dict stays deterministic and testable.

`GoogleCareersSource._make_process` changes from calling `get_project_settings()`
then `settings.set("ITEM_PIPELINES", …)` to: `ScrapySettings`-style construction
from the dict returned by `build_scrapy_settings()`, via
`from scrapy.settings import Settings as ScrapySettings; settings = ScrapySettings(values)`
then `CrawlerProcess(settings)`. The `_CRAWLED_ITEMS` collector mechanism is
**unchanged**; only how the settings object is produced changes.

#### 6.3.1 The policy guard

Lives in `backend/app/ingestion/middleware.py` (it imports Scrapy; §3 decision).

```python
from __future__ import annotations

import scrapy
from scrapy.exceptions import IgnoreRequest


class PolicyViolation(Exception):
    """A request escaped the crawl's permitted scope. Never swallowed."""


class PolicyGuardMiddleware:
    """Raise ``PolicyViolation`` if a request's URL is outside the permitted scope."""

    def process_spider_output(
        self,
        response: scrapy.http.Response,
        result: Iterable[scrapy.Request],  # simplest hook; see note
        spider: scrapy.Spider,
    ) -> Iterable[scrapy.Request]:
        ...
```

- We use `process_spider_output` rather than `allow_request` (a downloader
  middleware hook): the violation must **stop the crawl**, and raising from a
  spider middleware's `process_spider_output` does exactly that, whereas
  `allow_request` only means "skip this request" and would silently drop — the
  behaviour the anti-goals forbid. (Raise `PolicyViolation`; do not raise
  `IgnoreRequest`, which is the silent-drop path.)
- Permitted scope = `{spider.allowed_sitemap_urls}` (populated in `parse`, see
  §6.4) plus the sitemap URL itself (`spider.start_urls[0]`), which is requested
  by the engine before `parse` runs and is therefore never inspected by this
  middleware. A URL that is not a member raises `PolicyViolation`.
- Because the only requests the spider constructs today are sitemap-derived, this
  guard is a **regression test that runs in production on every crawl**, not a new
  restriction. It is what makes §6.1's "by construction" claim true by
  enforcement.
- Annotated fully for mypy strict: `Request`/`Response`/`Spider` types from
  Scrapy, `Iterable` from `collections.abc`, no bare `Any`.

### 6.4 Spider changes — `backend/app/ingestion/spiders/google_careers.py`

The spider currently has **no `__init__`**; `start_urls` is a class attribute.
Add:

```python
def __init__(self, *args: Any, **kwargs: Any) -> None:
    super().__init__(*args, **kwargs)
    self.allowed_sitemap_urls: set[str] = set()
```

- `parse()` adds each accepted sitemap `<loc>` to `self.allowed_sitemap_urls`
  **before** yielding the detail request for it.
- No change to extraction, the Tokyo filter, or `ID_PATTERN`.
- `start_urls` stays `[SITEMAP_URL]`. The sitemap fetch itself is a `start_url`,
  not a spider-output request, so it is not passed through the guard (see §6.3.1).

### 6.5 Run record — `crawl_runs`

Model — `backend/app/models/crawl_run.py`:

| Column | Type | Notes |
|---|---|---|
| `id` | `BigInteger().with_variant(Integer, "sqlite")` PK autoincrement | mirrors `Job.id` |
| `source` | `Text NOT NULL` | `google_careers` |
| `trigger` | `Text NOT NULL` | `cron` \| `manual` |
| `status` | `Text NOT NULL` | `running` \| `succeeded` \| `failed` \| `skipped_locked` |
| `started_at` | `DateTime(timezone=True) NOT NULL` | set by `IngestRun` from `now_provider` |
| `finished_at` | `DateTime(timezone=True) NULL` | `NULL` while `running` |
| `created` | `Integer NULL` | `IngestionResult.created` |
| `seen` | `Integer NULL` | `IngestionResult.seen` |
| `skipped_no_id` | `Integer NULL` | `IngestionResult.skipped_no_id` |
| `error` | `Text NULL` | `f"{type(exc).__name__}: {exc}"` — message, not traceback |

Index: `ix_crawl_runs_started_at` on `started_at` (PBI 8/9 query "last successful
run"). The `jobs` table is untouched. No `updated_at` (nothing updates rows;
`finish`/`fail` transition once, inside a single session).

Alembic revision `0004_crawl_runs.py`, `down_revision = "0003"`, following the
existing revision idiom.

Repository — `backend/app/repositories/crawl_run.py`:

```python
def start(self, session: Session, *, source: str, trigger: str, now: datetime) -> CrawlRun
def finish(self, session: Session, run: CrawlRun, result: IngestionResult, now: datetime) -> None
def fail(self, session: Session, run: CrawlRun, error: str, now: datetime) -> None
def record_skipped(self, session: Session, *, source: str, trigger: str, now: datetime) -> CrawlRun
```

- All methods take an explicit `session` and **do not commit**; `IngestRun` owns
  the transaction boundary (§6.7). This matches `JobRepository`'s stateless style
  (its methods take a session).
- `record_skipped` is a dedicated method (not `start` with a status override) so
  the `skipped_locked` row is not transiently `running`.
- **No `last_success()` in this PBI.** PBI 8 defines its own query shape; adding an
  uncalled method now would be untested dead code.

**Status transitions are explicit:** `running` → `succeeded` | `failed`.
`skipped_locked` rows are terminal and are written directly. A crashed process
leaves a `running` row with `finished_at IS NULL`; that is the *intended* signal
that a run died mid-flight, and PBI 8 treats a stale `running` row as "unknown",
never as a success.

### 6.6 Advisory lock — `backend/app/ingestion/locking.py`

```python
from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy.orm import Session

LOCK_KEY = 0x4A53_0006  # 'JS' + PBI 6; arbitrary, fixed, documented


@contextmanager
def ingestion_lock(session: Session) -> Iterator[bool]:
    """Yield True if this process holds the crawl lock.

    Postgres: ``pg_try_advisory_lock`` / released with ``pg_advisory_unlock`` on
    the same session in ``finally``; the lock also dies with the connection.
    SQLite (tests): always yields True — no cross-process concurrency to guard.
    """
```

- Dialect check via `session.get_bind().dialect.name == "postgresql"`, matching
  the `.with_variant(..., "sqlite")` pattern in `models/job.py`.
- Advisory locks are **session-scoped**. Because §6.7 threads one session through
  the lock, the run row, and the crawl, the lock is held on the same connection
  the crawl commits on. If the process dies, the connection closes and the lock
  releases — no stale-lock recovery needed.
- **Exception-safety:** the `finally` calls `pg_advisory_unlock` only when the
  lock was acquired; `IngestRun` (not this module) is responsible for closing the
  run row on every path.

### 6.7 `IngestRun` — `backend/app/ingestion/run.py`

```python
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy.orm import Session

from app.ingestion.service import IngestionResult


@dataclass(frozen=True, slots=True)
class RunOutcome:
    exit_code: int          # 0 success, 1 crawl failed, 2 skipped (lock held)
    result: IngestionResult | None  # None when skipped or failed
    error: str | None       # set when exit_code == 1
    skipped_locked: bool    # True when exit_code == 2


@dataclass(frozen=True)
class IngestRun:
    source: JobSource
    session_factory: Callable[[], Session]
    trigger: str                                   # "cron" | "manual"
    now_provider: Callable[[], datetime] | None = None

    def run(self) -> RunOutcome: ...
```

Body (§5 diagram, verbatim ordering):

```python
session = self.session_factory()
now = self._now()
try:
    with ingestion_lock(session) as held:
        if not held:
            crawl_runs.record_skipped(session, source=self.source.name,
                                      trigger=self.trigger, now=now)
            session.commit()
            return RunOutcome(2, None, None, skipped_locked=True)
        run = crawl_runs.start(session, source=self.source.name,
                               trigger=self.trigger, now=now)
        try:
            result = IngestionService(self.source, lambda: session,
                                      now_provider=lambda: now).run(session=session)
        except BaseException as exc:            # noqa: BLE001 — re-raised below
            session.rollback()
            error = f"{type(exc).__name__}: {exc}"
            crawl_runs.fail(session, run, error, now)
            session.commit()
            return RunOutcome(1, None, error, skipped_locked=False)
        crawl_runs.finish(session, run, result, now)
        session.commit()
        return RunOutcome(0, result, None, skipped_locked=False)
finally:
    session.close()
```

- The `lambda: now` passed as `IngestionService`'s `session_factory` returns the
  *same* session, so a future refactor of `run()` that re-opens is caught by diff,
  while the signature stays compatible. (Alternative considered: remove
  `session_factory` from `IngestionService` entirely — rejected, it would touch
  every existing test for no PBI 6 benefit.)
- `session.rollback()` before `fail()` discards any partial crawl writes (the
  job-row writes in the failing batch), then the failure row commits on a clean
  transaction. A run that failed halfway writes **no** job rows — consistent with
  the current all-or-nothing `IngestionService` commit.
- `BaseException` (not `Exception`) so a `KeyboardInterrupt` / `SystemExit` still
  closes the run row.
- `now` captured **once** and used for the run row *and* the jobs (single clock
  source, §4). `IngestionService`'s default `now_provider` is replaced.

### 6.8 CLI wiring and cron — `backend/app/ingest.py`, `Makefile`

```python
def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Ingest jobs from permitted feeds")
    parser.add_argument("--trigger", choices=["cron", "manual"], default="manual")
    args = parser.parse_args(argv)
    return run_ingestion(trigger=args.trigger)
```

- `--limit` is **removed** (§3). `run_ingestion` becomes:

  ```python
  def run_ingestion(*, trigger: str = "manual") -> int:
      outcome = IngestRun(build_source(), _session_factory(), trigger).run()
      ...  # print; return outcome.exit_code
  ```

  `build_source` and `make_engine` remain module-level seams; `test_ingest_cli.py`
  keeps monkeypatching them. `run_ingestion`'s signature change (`limit` out,
  keyword-only `trigger` in) is the one test-visible break; the existing tests are
  updated to the new signature.
- Printed output: unchanged on success
  (`ingestion complete: created=… seen=… skipped_no_id=…`); on skip
  (`ingestion skipped: another run holds the lock`); on failure
  (`ingestion failed: {error}`) — replacing today's hard-coded
  `"sitemap unreachable ({exc})"` message, which assumed `FetchError`.
- Exit codes: **0** success, **1** crawl failed, **2** skipped. Distinct codes make
  cron's failure signal meaningful — a skipped run is not a failure.
- `Makefile` `ingest` target forwards the trigger:

  ```make
  ingest:
  	uv run --package jobsearch-backend python -m app.ingest --trigger $(or $(TRIGGER),manual)
  ```

- Documented crontab line (`README.md` and below):

  ```
  17 6 * * * cd /home/jason/job-search && /usr/bin/make ingest TRIGGER=cron >> /var/log/jobsearch-ingest.log 2>&1
  ```

- Documented gotchas: absolute paths (`which make uv docker`); the Docker daemon
  must be up (`docker compose ps --status running` precheck recommended); the log
  file must be writable.
- **A run whose process never started is not recorded.** The README states the DB
  record covers *attempts that reached the app*; a cron entry that fails to launch
  (Docker down) shows only in the log — the gap PBI 9's host-level metrics exist to
  close.
- **Missed runs** (laptop asleep) are tolerated; cron without `Persistent`
  catch-up skips them, and the next run catches up on data. PBI 8 must therefore
  define "disappeared" over **observed successful crawl runs**
  (`crawl_runs.status='succeeded'` windows), never wall-clock days.
- **A daily cadence makes the PBI 8 window coarse.** At six hours, three
  confirmations span ~12h; daily, they span ~2 days — so a posting that is
  filled at 06:00 is not flagged as gone until roughly 06:00 two days later.
  That is acceptable for a personal tool, but it must be a **stated parameter** in
  PBI 8, not an accident of the cron line: PBI 8's confirmation rule should be
  expressed in *successful runs* (`seen missing across N successful crawls`) so
  changing this cadence changes detection latency and nothing else.

### 6.9 `croniter`

Added to **validate** the documented cadence in a test
(`test_cron_schedule.py`): asserts `17 6 * * *` is a valid expression and that its
next occurrences are 24 hours apart. It is not used at runtime in PBI 6.

**The cron expression has a single source of truth.** Rather than repeating the
string in the README, the Makefile, and the test, define it once in
`backend/app/ingestion/schedule.py`:

```python
SCHEDULE = "17 6 * * *"  # daily at 06:17 host-local (§3)
```

and have the test parse *that* constant. The README and the documented crontab
line are derived from it and **must be updated together** — called out because a
README that drifts from `SCHEDULE` is exactly how a cadence silently changes.

## 7. Testing strategy

| Test | Where | Marker |
|---|---|---|
| `build_scrapy_settings` pins politeness values, `RETRY_TIMES == 0`, `ROBOTSTXT_OBEY is False` (present in dict), `LOG_ENABLED` mirrors `verbose` | `test_scrapy_settings.py` | default |
| `registrable_host` / `budget_for`; unknown host raises `UnconfiguredHostError` | `test_policy.py` | default |
| `PolicyGuardMiddleware` raises `PolicyViolation` on a non-member URL and passes sitemap URLs | `test_policy_guard.py` | default |
| Spider records accepted `<loc>`s into `allowed_sitemap_urls` | `test_google_careers_spider.py` (extend) | default |
| `crawl_runs` model + repository CRUD (`start`/`finish`/`fail`/`record_skipped`), no commit inside repo | `test_crawl_run_model.py` | default |
| `ingestion_lock` yields True on SQLite; `pg_advisory_unlock` called only when acquired (fake session) | `test_locking.py` | default |
| `IngestRun`: success, failure (rollback + `failed` row, no job rows), lock-held skip (exit 2 + `skipped_locked` row), `KeyboardInterrupt` closes row | `test_ingest_run.py` | default (SQLite) |
| `IngestionService.run(session=...)` commits on the shared session; existing no-arg path unchanged | `test_ingestion_service.py` (extend) | default |
| CLI exit codes 0/1/2, `--trigger` in the record, `--limit` gone | `test_ingest_cli.py` (extend) | default |
| Advisory lock mutual exclusion on real Postgres | `test_locking_postgres.py` | **`ingest`** (existing marker) |
| `croniter` accepts `SCHEDULE`; 24-hour spacing | `test_cron_schedule.py` | default |
| One real crawl still yields non-empty | `test_ingest_integration.py` (existing) | `ingest` |

- **Marker:** no new marker. The Postgres lock test reuses the existing `ingest`
  marker (`pyproject.toml`), exactly as `test_migration_0003.py` does — reusing it
  avoids an unregistered-marker warning and keeps one opt-in bucket.
- `make test` stays network- and Postgres-free.

## 8. Verification (end-to-end)

1. `make lint` — clean.
2. `make typecheck` — strict mypy over `backend/app` and `shared/jobsearch_shared`.
3. `make test` — all default tests pass; the `ingest`-marked tests are deselected.
4. `make db-up && make migrate` — `crawl_runs` exists; `\d crawl_runs` shows the
   index.
5. `make ingest` (default trigger `manual`) — prints counts; a `crawl_runs` row
   lands with `status='succeeded'`, `trigger='manual'`, counts populated.
6. `make ingest TRIGGER=cron` — row has `trigger='cron'`.
7. Run two `make ingest` concurrently — one exits **0** with `succeeded`; the
   other exits **2** and writes `skipped_locked`.
8. Force a failure (fake source raises) via the CLI seam — exit **1**,
   `status='failed'`, `error` populated, no partial job rows.
9. Install the crontab line; wait for a scheduled run; confirm a `trigger='cron'`
   row.
10. Confirm the API still serves `/jobs` throughout (separate processes; no
    import).

## 9. Out of scope

- **Retry / exponential backoff** — PBI 7. `RETRY_TIMES=0` here is deliberate.
- **"Disappeared job" detection** — PBI 8; consumes `crawl_runs` and the policy
  guard's failure semantics.
- **Metrics / dashboards for crawl health** — PBI 9; consumes the run record and
  Scrapy stats (`AUTOTHROTTLE_DEBUG` is left visible for it).
- **Hosting** — Fly/Neon/Vercel/GitHub-Actions migration is a **config change**,
  not this PBI. Local Docker Postgres and a local crontab are the target. Forward
  obligations recorded only: psycopg needs a libpq/TLS-capable build before Neon,
  and crawl/migration must use a direct (non-pooled) connection.
- **Scraping job bodies / descriptions** — reopens §6.1's policy (PBI 3 §2.1).
- **A second source** — the budget registry anticipates it; nothing implements it.
- **Scheduler UI / job queue / Celery / APScheduler** — rejected in §2.

## 10. Open questions for the user

None outstanding. The three questions raised at review were answered on
2026-10-27:

| Question | Answer |
|---|---|
| Keep `croniter`? | **Keep** — with `SCHEDULE` as the single source of truth (§6.9). |
| `DOWNLOAD_DELAY`? | **2.0s** — unchanged (§6.2). |
| Cron cadence? | **Daily** (`17 6 * * *`) as a starter; PBI 8's window is expressed in successful runs so this can change without redesign (§3, §6.8). |

## Appendix A — Resolved during builder review

| Finding | Resolution |
|---|---|
| Lock/run-row session vs. `IngestionService`'s own session | One session threaded through; `IngestionService.run()` gains optional `session` (§3, §6.7). |
| `ROBOTSTXT_OBEY` "absent or False" | Pinned to explicit `False`; corrected spec's false claim that Scrapy defaults it to `True` — it defaults to `False` today. (§4, §6.1, §6.3, test row) |
| `PolicyGuardMiddleware` had no home and can't live in a no-Scrapy module | New `ingestion/middleware.py`; registered by dotted path (§3, §6.3.1). |
| Guard hook `allow_request` would silently drop | Use `process_spider_output`, raise `PolicyViolation` (§6.3.1). |
| Spider has no `__init__` | Add one that initializes `allowed_sitemap_urls` (§6.4). |
| `make ingest TRIGGER=cron` was shown but not wired | Makefile forwards `$(TRIGGER)`; `--trigger` threaded through `main()` (§6.8). |
| `skipped_locked` row had no creation method | Dedicated `record_skipped` (§6.5). |
| Who formats `error`; old message assumed `FetchError` | `f"{type(exc).__name__}: {exc}"`; CLI message generalized (§6.5, §6.8). |
| `RunOutcome` undefined | Defined dataclass (§6.7). |
| `--limit` dead code claimed to "apply to the record" | `--limit` removed entirely (§3, §6.8). |
| `last_success()` added but recommended deferred | Removed; PBI 8 owns it (§6.5). |
| New `integration` marker unregistered | Reuse existing `ingest` marker (§7). |
| `COMMON_FORBID`/`URL_FILTER` are not Scrapy settings | Removed; guard is a spider middleware via `SPIDER_MIDDLEWARES` (§6.3). |
| Mypy-strict: untyped `allow_request` sigs | All middleware signatures fully annotated (§6.3.1). |
| SQLite tz-naive comparison overlooked | Stated as a constraint (§4). |
| Two clock sources (`now` vs `now_provider`) | Single `now_provider`, one captured `now` (§4, §6.7). |
| `models/job.py` has no `from __future__` | Not required for new modules' correctness, but all new modules include it per repo convention (§4). |
