# PBI 6 — Crawl Scheduler Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a cron-driven run record and advisory lock to the existing ingestion path, pin Scrapy's politeness settings in a real settings module, and add a policy guard that raises if the crawl ever requests a URL outside its permitted scope.

**Architecture:** An `IngestRun` orchestrator opens one SQLAlchemy `Session`, acquires a Postgres advisory lock, writes a `crawl_runs` row via `CrawlRunRepository`, and threads that session through `IngestionService.run(session=…)`. A pure `policy.py` supplies per-host politeness budgets, a pure `scrapy_settings.py` turns one into a settings dict, and a `PolicyGuardMiddleware` (registered via `SPIDER_MIDDLEWARES`) raises `PolicyViolation` if any spider-output request is not a sitemap-`<loc>` member. The CLI gains `--trigger` and distinct exit codes 0/1/2; cron runs `make ingest TRIGGER=cron`.

**Tech Stack:** Python 3.13, SQLAlchemy 2.0 (typed `Mapped`), Alembic (`0004_crawl_runs`), Scrapy 2.19+ (`CrawlerProcess`, `Settings`, spider middleware), `croniter` (test-only cadence validation), pytest (SQLite `:memory:` unit tests + `ingest`-marked Postgres test), mypy strict, ruff, uv workspace.

**Spec:** [docs/superpowers/specs/2026-10-27-pbi6-crawl-scheduler-design.md](../specs/2026-10-27-pbi6-crawl-scheduler-design.md)

## Global Constraints

- Python `>=3.13`. Every new module — including the Scrapy middleware — begins with `from __future__ import annotations` and carries full annotations (mypy `disallow_untyped_defs`, `no_implicit_optional`); no bare `Any` in new code.
- Ruff `E, W, F, I, C, B`, double quotes, 88-char lines (`E501`, `E203` ignored), `line-ending = "auto"`.
- `make test` stays hermetic: no network, no live Postgres, no real cron. Every new unit runs on SQLite `:memory:`. The only Postgres-touching test reuses the existing `ingest` marker (no new marker).
- **SQLite timezone convention:** SQLite drops the offset from `DateTime(timezone=True)`. Tests comparing stored `started_at`/`finished_at` to a `FIXED_NOW` value compare against `FIXED_NOW.replace(tzinfo=None)`, exactly as `test_ingestion_service.py` does.
- **Single clock source:** `IngestRun` takes one `now_provider` and captures `now` once; that value stamps both the run row and the jobs.
- New dependency: `croniter` (add to `backend/pyproject.toml` `dependencies`). No scheduler library. `croniter` is used in a test only, never at runtime.
- The crawl remains **one command** (`python -m app.ingest`); no import between `app/ingestion` and `app.api`/`app.main` in either direction.
- `jobs` table and `Job` model are untouched. No `updated_at` on `crawl_runs`.

## Review Focus

1. **A `running` row whose process dies must be distinguishable from a live run.** `finished_at IS NULL` is the intended signal; a crashed process must leave a `running` row with `finished_at NULL`, and PBI 8 will treat a stale `running` row as "unknown". No code path may mark a `running` row `succeeded` without a crawl having returned. — Task 4 (`IngestRun` failure: `KeyboardInterrupt` still calls `fail`; `finished_at` stays `NULL` until `finish`/`fail`).
2. **A URL the spider constructs outside the sitemap must *stop* the crawl, not silently skip it.** `PolicyGuardMiddleware.process_spider_output` must *raise* `PolicyViolation` (not `IgnoreRequest`); the anti-goal is a silent drop that empties the crawl indistinguishably from an empty feed. — Task 7 (`test_policy_guard.py`: non-member URL raises `PolicyViolation`, member URL passes unchanged).
3. **`ROBOTSTXT_OBEY` must be present and `False` in the returned dict, never merely absent.** A future Scrapy that flips its default must not silently empty the crawl. Assert `settings["ROBOTSTXT_OBEY"] is False` (truthiness, not equality) so a dropped key fails. — Task 6 (`test_scrapy_settings.py`).
4. **A second source with no registered budget must fail loudly at first crawl, not crawl on permissive defaults.** `budget_for` on an unknown host raises `UnconfiguredHostError`. — Task 5 (`test_policy.py`).
5. **Two concurrent runs must not both crawl.** On Postgres the advisory lock guarantees one holds and the other records `skipped_locked`; a skipped run exits 2 (not a "failure"). — Task 3 (SQLite lock always yields `True`) + Task 4 (lock-held `IngestRun` returns exit 2 + `skipped_locked` row) + Task 9 (Postgres mutual-exclusion).

---

### Task 1: Add the `crawl_runs` model

**Files:**
- Create: `backend/app/models/crawl_run.py`
- Modify: `backend/app/models/__init__.py` (export `CrawlRun`)
- Test: `backend/tests/test_crawl_run_model.py` (new)

**Interfaces:**
- Consumes: `Base` (from `app.models.base`); the `BigInteger().with_variant(Integer, "sqlite")` PK idiom from `app/models/job.py`.
- Produces: `CrawlRun` ORM model — `__tablename__ = "crawl_runs"` — with columns and the `ix_crawl_runs_started_at` index described below. Imported by the repository (Task 2) and the Alembic metadata (via `app.models.__init__`).

  Columns (exact names/types): `id` (`BigInteger().with_variant(Integer, "sqlite")` PK autoincrement); `source` (`Text`, `nullable=False`); `trigger` (`Text`, `nullable=False`); `status` (`Text`, `nullable=False`); `started_at` (`DateTime(timezone=True)`, `nullable=False`); `finished_at` (`DateTime(timezone=True)`, `nullable=True`); `created` (`Integer`, `nullable=True`); `seen` (`Integer`, `nullable=True`); `skipped_no_id` (`Integer`, `nullable=True`); `error` (`Text`, `nullable=True`). Index `ix_crawl_runs_started_at` on `started_at`.

- [x] **Step 1: Write the failing tests**

Create `backend/tests/test_crawl_run_model.py`:

```python
from sqlalchemy import create_engine, inspect

from app.models import Base


def test_crawl_runs_table_has_expected_columns() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    insp = inspect(engine)
    assert "crawl_runs" in insp.get_table_names()

    cols = {c["name"]: c for c in insp.get_columns("crawl_runs")}
    assert set(cols) == {
        "id",
        "source",
        "trigger",
        "status",
        "started_at",
        "finished_at",
        "created",
        "seen",
        "skipped_no_id",
        "error",
    }
    assert cols["source"]["nullable"] is False
    assert cols["trigger"]["nullable"] is False
    assert cols["status"]["nullable"] is False
    assert cols["started_at"]["nullable"] is False
    assert cols["finished_at"]["nullable"] is True
    assert cols["created"]["nullable"] is True
    assert cols["seen"]["nullable"] is True
    assert cols["skipped_no_id"]["nullable"] is True
    assert cols["error"]["nullable"] is True


def test_crawl_runs_has_started_at_index() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    insp = inspect(engine)
    index_names = {ix["name"] for ix in insp.get_indexes("crawl_runs")}
    assert "ix_crawl_runs_started_at" in index_names
```

- [x] **Step 2: Run tests to verify they fail**

Run: `uv run pytest backend/tests/test_crawl_run_model.py -v`
Expected: FAIL — `test_crawl_runs_table_has_expected_columns`: `AssertionError: "crawl_runs" not in []` (table not created); `test_crawl_runs_has_started_at_index`: same.

- [x] **Step 3: Create `backend/app/models/crawl_run.py`**

Follow `models/job.py`'s style exactly (`from __future__ import annotations` is optional here since `job.py` omits it; keep the `Mapped`/`mapped_column` typed style). Add to `backend/app/models/__init__.py` the import and `__all__` entry `"CrawlRun"`.

- [x] **Step 4: Run tests to verify they pass**

Run: `uv run pytest backend/tests/test_crawl_run_model.py -v`
Expected: PASS (2 tests).

- [x] **Step 5: Commit**

```bash
git add backend/app/models/crawl_run.py backend/app/models/__init__.py backend/tests/test_crawl_run_model.py
git commit -m "feat(pbi6): add crawl_runs model with started_at index"
```

---

### Task 2: Add the `crawl_runs` Alembic revision `0004`

**Files:**
- Create: `backend/alembic/versions/0004_crawl_runs.py`

**Interfaces:**
- Consumes: the `crawl_runs` columns from Task 1; the `0003` revision idiom (`backend/alembic/versions/0003_job_identity.py`).
- Produces: Alembic `revision = "0004"`, `down_revision = "0003"`; `upgrade()`/`downgrade()` annotated `-> None`. `upgrade()` creates the table + `ix_crawl_runs_started_at` and `downgrade()` drops both.

- [x] **Step 1: Write the migration**

Create `backend/alembic/versions/0004_crawl_runs.py`, mirroring `0002_jobs.py`'s `op.create_table` style. `id` uses `sa.BigInteger()` (SQLite autoincrement is handled by the ORM `.with_variant`, not by this migration, which targets Postgres's `BIGINT`). Include the `ix_crawl_runs_started_at` index on `started_at`.

- [x] **Step 2: Verify the migration applies and reverses**

Run against a scratch SQLite DB (migration must be dialect-safe):

```bash
rm -f /tmp/pbi6_migration.db
DATABASE_URL=sqlite:////tmp/pbi6_migration.db uv run --package jobsearch-backend alembic -c backend/alembic.ini upgrade head
DATABASE_URL=sqlite:////tmp/pbi6_migration.db uv run --package jobsearch-backend alembic -c backend/alembic.ini downgrade 0003
DATABASE_URL=sqlite:////tmp/pbi6_migration.db uv run --package jobsearch-backend alembic -c backend/alembic.ini upgrade head
```

Expected: three commands exit 0. (SQLite doesn't run the `ingest`-gated assertions; those live in Task 10 against real Postgres.)

- [x] **Step 3: Commit**

```bash
git add backend/alembic/versions/0004_crawl_runs.py
git commit -m "feat(pbi6): add crawl_runs alembic revision 0004"
```

---

### Task 3: Add `CrawlRunRepository`

**Files:**
- Create: `backend/app/repositories/crawl_run.py`
- Test: `backend/tests/test_crawl_run_repository.py` (new)

**Interfaces:**
- Consumes: `CrawlRun` (Task 1), `IngestionResult` (from `app.ingestion.service`), SQLAlchemy `Session`.
- Produces: `CrawlRunRepository` with stateless methods (all take an explicit `session`, none commit):
  - `start(session: Session, *, source: str, trigger: str, now: datetime) -> CrawlRun` — inserts a row with `status="running"`, `started_at=now`, `finished_at=None`, all count columns `None`.
  - `finish(session: Session, run: CrawlRun, result: IngestionResult, now: datetime) -> None` — sets `status="succeeded"`, `finished_at=now`, and copies `created`/`seen`/`skipped_no_id` from `result`.
  - `fail(session: Session, run: CrawlRun, error: str, now: datetime) -> None` — sets `status="failed"`, `finished_at=now`, `error=error` (count columns stay `None`).
  - `record_skipped(session: Session, *, source: str, trigger: str, now: datetime) -> CrawlRun` — inserts a row with `status="skipped_locked"`, `started_at=now`, `finished_at=now` (a terminal row, never transiently `running`), count columns `None`.

- [x] **Step 1: Write the failing tests**

Create `backend/tests/test_crawl_run_repository.py`:

```python
from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.ingestion.service import IngestionResult
from app.models import Base, CrawlRun
from app.repositories.crawl_run import CrawlRunRepository

FIXED_NOW = datetime(2026, 10, 27, 6, 17, 0, tzinfo=timezone.utc)
FINISHED_NOW = datetime(2026, 10, 27, 6, 19, 0, tzinfo=timezone.utc)


@pytest.fixture()
def session() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        yield s


def _all(session: Session) -> list[CrawlRun]:
    return list(session.scalars(select(CrawlRun)))


def test_start_then_finish_writes_complete_row(session: Session) -> None:
    repo = CrawlRunRepository()
    run = repo.start(session, source="google_careers", trigger="cron", now=FIXED_NOW)
    session.flush()
    assert run.status == "running"
    assert run.started_at == FIXED_NOW.replace(tzinfo=None)
    assert run.finished_at is None

    repo.finish(
        session,
        run,
        IngestionResult(created=3, seen=1, skipped_no_id=0),
        now=FINISHED_NOW,
    )
    session.flush()
    assert run.status == "succeeded"
    assert run.finished_at == FINISHED_NOW.replace(tzinfo=None)
    assert run.created == 3
    assert run.seen == 1
    assert run.skipped_no_id == 0
    assert len(_all(session)) == 1


def test_fail_writes_error_and_counts_stay_null(session: Session) -> None:
    repo = CrawlRunRepository()
    run = repo.start(session, source="google_careers", trigger="manual", now=FIXED_NOW)
    repo.fail(session, run, "FetchError: boom", now=FINISHED_NOW)
    session.flush()
    assert run.status == "failed"
    assert run.error == "FetchError: boom"
    assert run.finished_at == FINISHED_NOW.replace(tzinfo=None)
    assert run.created is None
    assert run.seen is None
    assert run.skipped_no_id is None


def test_record_skipped_is_terminal_not_running(session: Session) -> None:
    repo = CrawlRunRepository()
    row = repo.record_skipped(session, source="google_careers", trigger="cron", now=FIXED_NOW)
    session.flush()
    assert row.status == "skipped_locked"
    assert row.started_at == FIXED_NOW.replace(tzinfo=None)
    assert row.finished_at == FIXED_NOW.replace(tzinfo=None)
```

- [x] **Step 2: Run tests to verify they fail**

Run: `uv run pytest backend/tests/test_crawl_run_repository.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.repositories.crawl_run'`.

- [x] **Step 3: Implement `CrawlRunRepository` in `backend/app/repositories/crawl_run.py`**

Follow `repositories/job.py`'s stateless style (constructor takes nothing, methods build ORM objects and `session.add(...)`). `finish` reads `result.created`, `result.seen`, `result.skipped_no_id`. No method calls `session.commit()`.

- [x] **Step 4: Run tests to verify they pass**

Run: `uv run pytest backend/tests/test_crawl_run_repository.py -v`
Expected: PASS (3 tests).

- [x] **Step 5: Commit**

```bash
git add backend/app/repositories/crawl_run.py backend/tests/test_crawl_run_repository.py
git commit -m "feat(pbi6): add CrawlRunRepository (start/finish/fail/record_skipped)"
```

---

### Task 4: Add the advisory lock (`locking.py`)

**Files:**
- Create: `backend/app/ingestion/locking.py`
- Test: `backend/tests/test_locking.py` (new)

**Interfaces:**
- Consumes: SQLAlchemy `Session` and its bound dialect.
- Produces: `LOCK_KEY = 0x4A53_0006` (a documented constant) and a `@contextmanager` `ingestion_lock(session: Session) -> Iterator[bool]` yielding `True` when the lock is held. On Postgres it issues `pg_try_advisory_lock(LOCK_KEY)`; when acquired it yields `True` and runs `pg_advisory_unlock(LOCK_KEY)` in `finally`. On any other dialect (SQLite) it yields `True` immediately with no acquisition. It must never release a lock it did not acquire.

- [x] **Step 1: Write the failing tests**

Create `backend/tests/test_locking.py`:

```python
from app.ingestion.locking import LOCK_KEY, ingestion_lock


class FakeDialect:
    name = "sqlite"


class FakeBind:
    dialect = FakeDialect()


class FakeSession:
    def get_bind(self) -> FakeBind:
        return FakeBind()


def test_lock_yields_true_on_sqlite() -> None:
    with ingestion_lock(FakeSession()) as held:  # type: ignore[arg-type]
        assert held is True


def test_lock_key_is_fixed() -> None:
    assert LOCK_KEY == 0x4A53_0006
```

- [x] **Step 2: Run tests to verify they fail**

Run: `uv run pytest backend/tests/test_locking.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.ingestion.locking'`.

- [x] **Step 3: Implement `ingestion_lock`**

The Postgres branch runs `session.execute(text("SELECT pg_try_advisory_lock(:key)"), {"key": LOCK_KEY})` and, only when the returned boolean is `True`, runs `session.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": LOCK_KEY})` in `finally`. Dialect dispatch is `session.get_bind().dialect.name == "postgresql"`. Ensure mypy-strict passes (the contextmanager yields `bool`; the `finally` runs inside the generator's `try`).

- [x] **Step 4: Run tests to verify they pass**

Run: `uv run pytest backend/tests/test_locking.py -v`
Expected: PASS (2 tests).

- [x] **Step 5: Commit**

```bash
git add backend/app/ingestion/locking.py backend/tests/test_locking.py
git commit -m "feat(pbi6): add ingestion advisory lock contextmanager"
```

---

### Task 5: Add rate budgets (`policy.py`)

**Files:**
- Create: `backend/app/ingestion/policy.py`
- Test: `backend/tests/test_policy.py` (new)

**Interfaces:**
- Consumes: nothing (pure module, no Scrapy import).
- Produces:
  - `class UnconfiguredHostError(LookupError)` — raised when a host has no budget.
  - `@dataclass(frozen=True, slots=True) class RateBudget` with fields `download_delay: float`, `concurrent_requests_per_domain: int`, `autothrottle_target_concurrency: float`, `autothrottle_max_delay: float`.
  - `GOOGLE_BUDGET = RateBudget(download_delay=2.0, concurrent_requests_per_domain=1, autothrottle_target_concurrency=1.0, autothrottle_max_delay=30.0)`.
  - `BUDGETS: Mapping[str, RateBudget] = {"google.com": GOOGLE_BUDGET}`.
  - `registrable_host(url: str) -> str` — two-label suffix of the URL's host (`www.google.com` → `google.com`).
  - `budget_for(url: str) -> RateBudget` — looks up `BUDGETS[registrable_host(url)]`; raises `UnconfiguredHostError` for unknown hosts.

- [x] **Step 1: Write the failing tests**

Create `backend/tests/test_policy.py`:

```python
import pytest

from app.ingestion.policy import (
    GOOGLE_BUDGET,
    UnconfiguredHostError,
    budget_for,
    registrable_host,
)


def test_registrable_host_strips_to_two_labels() -> None:
    assert registrable_host("https://careers.google.com/jobs/sitemap") == "google.com"
    assert registrable_host("https://www.google.com/x") == "google.com"


def test_budget_for_known_host() -> None:
    assert budget_for("https://careers.google.com/jobs/results/1-a/") == GOOGLE_BUDGET


def test_budget_for_unknown_host_raises() -> None:
    with pytest.raises(UnconfiguredHostError):
        budget_for("https://jobs.example.com/x")


def test_google_budget_values_are_pinned() -> None:
    assert GOOGLE_BUDGET.download_delay == 2.0
    assert GOOGLE_BUDGET.concurrent_requests_per_domain == 1
    assert GOOGLE_BUDGET.autothrottle_target_concurrency == 1.0
    assert GOOGLE_BUDGET.autothrottle_max_delay == 30.0
```

- [x] **Step 2: Run tests to verify they fail**

Run: `uv run pytest backend/tests/test_policy.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.ingestion.policy'`.

- [x] **Step 3: Implement `backend/app/ingestion/policy.py`**

`registrable_host` parses with `urlsplit(url).netloc` (strip a `www.` prefix, then take the last two labels separated by `.`). Docstrings name the public-suffix-list as the upgrade path for multi-label suffixes (per spec §6.2).

- [x] **Step 4: Run tests to verify they pass**

Run: `uv run pytest backend/tests/test_policy.py -v`
Expected: PASS (4 tests).

- [x] **Step 5: Commit**

```bash
git add backend/app/ingestion/policy.py backend/tests/test_policy.py
git commit -m "feat(pbi6): add per-host rate budgets (policy.py)"
```

---

### Task 6: Add Scrapy settings (`scrapy_settings.py`) and rewire `_make_process`

**Files:**
- Create: `backend/app/ingestion/scrapy_settings.py`
- Modify: `backend/app/ingestion/sources/google_careers.py` (`_make_process`, imports)
- Test: `backend/tests/test_scrapy_settings.py` (new)

**Interfaces:**
- Consumes: `budget_for`/`registrable_host` (Task 5).
- Produces: `build_scrapy_settings(*, verbose: bool = False, source_url: str = "https://careers.google.com/jobs/sitemap") -> dict[str, object]`.

  The dict's keys/values (exact): `ITEM_PIPELINES` → `{"app.ingestion.sources.google_careers._CrawlItemsPipeline": 1}`; `SPIDER_MIDDLEWARES` → `{"app.ingestion.middleware.PolicyGuardMiddleware": 543}`; `LOG_ENABLED` → `verbose`; `LOG_LEVEL` → `"INFO"` if `verbose` else `"DEBUG"`; `DOWNLOAD_DELAY` → `budget.download_delay` (resolved from `budget_for(source_url)`); `RANDOMIZE_DOWNLOAD_DELAY` → `True`; `CONCURRENT_REQUESTS` → `1`; `CONCURRENT_REQUESTS_PER_DOMAIN` → `1`; `AUTOTHROTTLE_ENABLED` → `True`; `AUTOTHROTTLE_TARGET_CONCURRENCY` → `1.0`; `AUTOTHROTTLE_MAX_DELAY` → `30.0`; `AUTOTHROTTLE_DEBUG` → `verbose`; `RETRY_TIMES` → `0`; `ROBOTSTXT_OBEY` → `False`.

- [x] **Step 1: Write the failing tests**

Create `backend/tests/test_scrapy_settings.py`:

```python
from app.ingestion.scrapy_settings import build_scrapy_settings


def test_settings_include_politeness_values() -> None:
    s = build_scrapy_settings()
    assert s["DOWNLOAD_DELAY"] == 2.0
    assert s["RANDOMIZE_DOWNLOAD_DELAY"] is True
    assert s["CONCURRENT_REQUESTS"] == 1
    assert s["CONCURRENT_REQUESTS_PER_DOMAIN"] == 1
    assert s["AUTOTHROTTLE_ENABLED"] is True
    assert s["AUTOTHROTTLE_TARGET_CONCURRENCY"] == 1.0
    assert s["AUTOTHROTTLE_MAX_DELAY"] == 30.0


def test_retry_times_is_zero() -> None:
    assert build_scrapy_settings()["RETRY_TIMES"] == 0


def test_robotstxt_obey_is_explicitly_false() -> None:
    # Present AND False: truthiness catches a dropped key and a stale True.
    assert build_scrapy_settings()["ROBOTSTXT_OBEY"] is False


def test_log_enabled_mirrors_verbose() -> None:
    assert build_scrapy_settings(verbose=True)["LOG_ENABLED"] is True
    assert build_scrapy_settings(verbose=False)["LOG_ENABLED"] is False
    assert build_scrapy_settings(verbose=True)["LOG_LEVEL"] == "INFO"
    assert build_scrapy_settings(verbose=False)["LOG_LEVEL"] == "DEBUG"


def test_item_pipelines_and_spider_middlewares_registered() -> None:
    s = build_scrapy_settings()
    assert s["ITEM_PIPELINES"] == {
        "app.ingestion.sources.google_careers._CrawlItemsPipeline": 1
    }
    assert s["SPIDER_MIDDLEWARES"] == {
        "app.ingestion.middleware.PolicyGuardMiddleware": 543
    }
```

- [x] **Step 2: Run tests to verify they fail**

Run: `uv run pytest backend/tests/test_scrapy_settings.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.ingestion.scrapy_settings'`.

- [x] **Step 3: Implement `build_scrapy_settings`**

A pure function; resolve `budget = budget_for(source_url)` at the top. Return value uses the exact values above. Then rewrite `GoogleCareersSource._make_process` to build the settings from this dict rather than `get_project_settings()`:

```python
from scrapy.settings import Settings as ScrapySettings

def _make_process(self) -> CrawlerProcess:
    values = build_scrapy_settings(verbose=self.verbose)
    settings = ScrapySettings(values)
    return CrawlerProcess(settings)
```

Remove the now-unused `get_project_settings` import. The `_CRAWLED_ITEMS` collector and `_run_crawl` are untouched.

- [x] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest backend/tests/test_scrapy_settings.py -v`
Expected: PASS (5 tests).

- [x] **Step 5: Commit**

```bash
git add backend/app/ingestion/scrapy_settings.py backend/app/ingestion/sources/google_careers.py backend/tests/test_scrapy_settings.py
git commit -m "feat(pbi6): add scrapy settings module and rewire _make_process"
```

---

### Task 7: Add the policy guard middleware

**Files:**
- Create: `backend/app/ingestion/middleware.py`
- Test: `backend/tests/test_policy_guard.py` (new)

**Interfaces:**
- Consumes: Scrapy (`scrapy.http.Response`, `scrapy.Request`, `scrapy.Spider`), `collections.abc.Iterable`.
- Produces: `class PolicyViolation(Exception)` and `class PolicyGuardMiddleware` (a Scrapy *spider* middleware) with a fully-annotated `process_spider_output(self, response: scrapy.http.Response, result: Iterable[scrapy.Request], spider: scrapy.Spider) -> Iterable[scrapy.Request]`. It iterates `result`; for each `Request`, if `request.url` is not in `{*spider.allowed_sitemap_urls, spider.start_urls[0]}` it raises `PolicyViolation`, else yields it unchanged. It is registered by dotted path from `scrapy_settings.py` (Task 6), not imported by any pure module.

- [x] **Step 1: Write the failing tests**

Create `backend/tests/test_policy_guard.py`:

```python
import pytest
import scrapy

from app.ingestion.middleware import PolicyGuardMiddleware, PolicyViolation


class FakeSpider(scrapy.Spider):
    name = "fake"
    start_urls = ["https://careers.google.com/jobs/sitemap"]


def _request(url: str) -> scrapy.Request:
    return scrapy.Request(url)


def _response() -> scrapy.http.HtmlResponse:
    return scrapy.http.HtmlResponse(url="https://careers.google.com/jobs/sitemap", body=b"")


def test_passes_sitemap_member_urls() -> None:
    spider = FakeSpider()
    spider.allowed_sitemap_urls = {"https://careers.google.com/jobs/results/1-a/"}
    mw = PolicyGuardMiddleware()
    reqs = list(
        mw.process_spider_output(
            _response(),
            [_request("https://careers.google.com/jobs/results/1-a/")],
            spider,
        )
    )
    assert [r.url for r in reqs] == ["https://careers.google.com/jobs/results/1-a/"]


def test_raises_on_non_member_url() -> None:
    spider = FakeSpider()
    spider.allowed_sitemap_urls = {"https://careers.google.com/jobs/results/1-a/"}
    mw = PolicyGuardMiddleware()
    with pytest.raises(PolicyViolation):
        list(
            mw.process_spider_output(
                _response(),
                [_request("https://careers.google.com/jobs/results/999-other/")],
                spider,
            )
        )
```

- [x] **Step 2: Run tests to verify they fail**

Run: `uv run pytest backend/tests/test_policy_guard.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.ingestion.middleware'`.

- [x] **Step 3: Implement `PolicyGuardMiddleware`**

Fully annotate for mypy strict. The permitted set is computed once per call (`allowed = spider.allowed_sitemap_urls | {spider.start_urls[0]}`); for each request check membership and raise `PolicyViolation(f"...{request.url}...")` on the first non-member. Raise `PolicyViolation`, never `IgnoreRequest` (the latter silently drops — the forbidden behavior).

- [x] **Step 4: Run tests to verify they pass**

Run: `uv run pytest backend/tests/test_policy_guard.py -v`
Expected: PASS (2 tests).

- [x] **Step 5: Commit**

```bash
git add backend/app/ingestion/middleware.py backend/tests/test_policy_guard.py
git commit -m "feat(pbi6): add PolicyGuardMiddleware raising PolicyViolation"
```

---

### Task 8: Spider records `allowed_sitemap_urls`

**Files:**
- Modify: `backend/app/ingestion/spiders/google_careers.py` (`__init__`, `parse`, imports)
- Test: `backend/tests/test_google_careers_spider.py` (extend)

**Interfaces:**
- Consumes: nothing new (Scrapy `Spider`).
- Produces: `GoogleCareersSpider.__init__(self, *args: Any, **kwargs: Any) -> None` (adds `super().__init__` and `self.allowed_sitemap_urls: set[str] = set()`); `parse` adds each accepted `<loc>` URL to `self.allowed_sitemap_urls` **before** yielding its detail request. `start_urls`, extraction, Tokyo filter, and `ID_PATTERN` are unchanged.

- [x] **Step 1: Write the failing test**

Extend `backend/tests/test_google_careers_spider.py` with:

```python
def test_parse_records_accepted_locs_into_allowed_sitemap_urls() -> None:
    sitemap = _sitemap_response(
        [
            "https://careers.google.com/jobs/results/83683003800134342-software-engineering-manager/",
            "https://careers.google.com/jobs/results/123-program-manager/",
            "https://careers.google.com/jobs/results/456-software-engineer/",
        ]
    )
    spider = GoogleCareersSpider()
    list(spider.parse(sitemap))  # consume the generator
    assert spider.allowed_sitemap_urls == {
        "https://careers.google.com/jobs/results/83683003800134342-software-engineering-manager/",
        "https://careers.google.com/jobs/results/456-software-engineer/",
    }
```

(Reuses the existing `_sitemap_response` helper already in that file.)

- [x] **Step 2: Run the test to verify it fails**

Run: `uv run pytest backend/tests/test_google_careers_spider.py::test_parse_records_accepted_locs_into_allowed_sitemap_urls -v`
Expected: FAIL — `AttributeError: 'GoogleCareersSpider' object has no attribute 'allowed_sitemap_urls'`.

- [x] **Step 3: Implement `__init__` and update `parse`**

Add `from typing import Any` (already imported) and the `__init__`. In `parse`, inside the `if ROLE_PATTERN.search(url):` branch, add `self.allowed_sitemap_urls.add(url)` before the `yield scrapy.Request(...)`.

- [x] **Step 4: Run the test to verify it passes**

Run: `uv run pytest backend/tests/test_google_careers_spider.py -v`
Expected: PASS (all 7 existing tests + the new one).

- [x] **Step 5: Commit**

```bash
git add backend/app/ingestion/spiders/google_careers.py backend/tests/test_google_careers_spider.py
git commit -m "feat(pbi6): spider records allowed_sitemap_urls for the policy guard"
```

---

### Task 9: Add `IngestRun` orchestrator

**Files:**
- Create: `backend/app/ingestion/run.py`
- Test: `backend/tests/test_ingest_run.py` (new)

**Interfaces:**
- Consumes: `ingestion_lock` (Task 4), `CrawlRunRepository` (Task 3), `IngestionService` + `IngestionResult` (existing `app.ingestion.service`), `JobSource` (existing `app.ingestion.sources.base`).
- Produces: `@dataclass(frozen=True, slots=True) RunOutcome(exit_code: int, result: IngestionResult | None, error: str | None, skipped_locked: bool)` and `@dataclass(frozen=True) IngestRun(source: JobSource, session_factory: Callable[[], Session], trigger: str, now_provider: Callable[[], datetime] | None = None)` with `run(self) -> RunOutcome`. The `run()` body follows the spec §6.7 verbatim ordering (lock → skipped/start → service → finish/fail → commit; `finally: session.close()`; `BaseException` handler with rollback + `fail`).

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_ingest_run.py`. Use a shared in-memory engine behind `session_factory`, a `FakeSource` (one that yields a `JobDraft` and records whether `fetch` ran), and a fixed `now_provider`.

Key cases:
- **success** — `run()` returns `RunOutcome(0, result, None, skipped_locked=False)`; `result.created == 1`; a `crawl_runs` row with `status == "succeeded"`, `trigger == "cron"`, `started_at`/`finished_at` set, and counts `created==1`.
- **failure** — a source whose `fetch` raises `RuntimeError` returns `RunOutcome(1, None, "RuntimeError: boom", skipped_locked=False)`; the run row has `status == "failed"` and `error == "RuntimeError: boom"`; and **no `jobs` rows were written** (rollback discarded the partial batch).
- **lock held (skipped)** — inject an `ingestion_lock` that yields `False` (monkeypatch `app.ingestion.run.ingestion_lock`); `run()` returns `RunOutcome(2, None, None, skipped_locked=True)` and writes a `skipped_locked` row; the source's `fetch` was **never invoked**.
- **`KeyboardInterrupt`** — a source whose `fetch` raises `KeyboardInterrupt` returns `RunOutcome(1, None, ..., skipped_locked=False)` with the run row marked `failed` (the `BaseException` path still closes the row).

Use `from datetime import datetime, timezone`, `FIXED_NOW = datetime(2026, 10, 27, 6, 17, 0, tzinfo=timezone.utc)`, and compare stored timestamps to `FIXED_NOW.replace(tzinfo=None)`.

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest backend/tests/test_ingest_run.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.ingestion.run'`.

- [ ] **Step 3: Implement `IngestRun`**

Transcribe the spec §6.7 body exactly: one `session = self.session_factory()`; `now = self._now()`; the `try/with/finally` ordering; `IngestionService(self.source, lambda: session, now_provider=lambda: now).run(session=session)`. On caught `BaseException`, `session.rollback()`, format `error = f"{type(exc).__name__}: {exc}"`, `crawl_runs.fail(...)`, `session.commit()`, return `RunOutcome(1, None, error, skipped_locked=False)`. Add the `# noqa: BLE001` where the bare `except` is.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest backend/tests/test_ingest_run.py -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add backend/app/ingestion/run.py backend/tests/test_ingest_run.py
git commit -m "feat(pbi6): add IngestRun orchestrator with run record + advisory lock"
```

---

### Task 10: Give `IngestionService.run()` an optional `session`

**Files:**
- Modify: `backend/app/ingestion/service.py` (`run` signature + body)
- Test: `backend/tests/test_ingestion_service.py` (extend)

**Interfaces:**
- Consumes: nothing new.
- Produces: `IngestionService.run(self, session: Session | None = None) -> IngestionResult`. When `session` is `None`, behavior is exactly today's (open a session from `session_factory`, commit, close). When `session` is provided, use it and `session.commit()` on the shared session without closing it; the no-arg path is unchanged so existing tests stay green.

- [ ] **Step 1: Write the failing test**

Extend `backend/tests/test_ingestion_service.py` with:

```python
def test_run_with_shared_session_commits_without_closing(
    session_factory: Callable[[], Session],
) -> None:
    service = IngestionService(
        FakeSource([_draft("777")]), session_factory, now_provider=lambda: FIXED_NOW
    )
    with session_factory() as shared:
        result = service.run(session=shared)
        # run() committed on `shared`; a fresh session sees the row.
        assert result.created == 1

    with session_factory() as check:
        job = check.scalar(select(Job).where(Job.external_job_id == "777"))
        assert job is not None
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest backend/tests/test_ingestion_service.py::test_run_with_shared_session_commits_without_closing -v`
Expected: FAIL — `TypeError: IngestionService.run() got an unexpected keyword argument 'session'`.

- [ ] **Step 3: Implement the optional `session`**

Change the signature to `def run(self, session: Session | None = None) -> IngestionResult:`. If `session` is `None`, keep the current `session = self.session_factory()` + `finally: session.close()` behavior; if provided, use it and do not close it. The `IntegrityError`/rollback/read-and-bump logic is unchanged.

- [ ] **Step 4: Run the full service suite**

Run: `uv run pytest backend/tests/test_ingestion_service.py -v`
Expected: PASS (all 7 existing tests + the new one).

- [ ] **Step 5: Commit**

```bash
git add backend/app/ingestion/service.py backend/tests/test_ingestion_service.py
git commit -m "feat(pbi6): IngestionService.run accepts an optional shared session"
```

---

### Task 11: Wire the CLI (`--trigger`, exit codes) and the schedule constant

**Files:**
- Create: `backend/app/ingestion/schedule.py`
- Modify: `backend/app/ingest.py` (`main`, `run_ingestion`, imports)
- Modify: `Makefile` (`ingest` target)
- Test: `backend/tests/test_ingest_cli.py` (rewrite/extend), `backend/tests/test_cron_schedule.py` (new)

**Interfaces:**
- Consumes: `IngestRun` (Task 9), `build_source`/`make_engine` seams (existing).
- Produces:
  - `SCHEDULE = "17 6 * * *"` in `backend/app/ingestion/schedule.py` (single source of truth).
  - `run_ingestion(*, trigger: str = "manual") -> int` — builds `IngestRun(build_source(), _session_factory(), trigger).run()`, prints `ingestion complete: created=… seen=… skipped_no_id=…` / `ingestion skipped: another run holds the lock` / `ingestion failed: {error}`, returns `outcome.exit_code`.
  - `main(argv)` parses `--trigger {cron,manual}` (default `manual`); `--limit` is removed.
  - `Makefile` `ingest` target: `uv run --package jobsearch-backend python -m app.ingest --trigger $(or $(TRIGGER),manual)`.

- [ ] **Step 1: Write the failing tests**

Rewrite `backend/tests/test_ingest_cli.py` in full. It keeps the existing seams (`build_source`, `make_engine`) but now backends the CLI with `IngestRun`. Tests:
- **success** (`exit 0`, prints `created=1 seen=0 skipped_no_id=0`) — a `FakeSource` yielding one draft, an in-memory SQLite engine patched into `make_engine`, and `trigger` defaults to `manual`.
- **failure** (`exit 1`, prints `ingestion failed: RuntimeError: boom`) — a source whose `fetch` raises.
- **trigger flag reaches the record** — monkeypatch `run_ingestion` to capture the keyword arg: `ingest.main(["--trigger", "cron"])` calls `run_ingestion(trigger="cron")`.
- **`--limit` is gone** — `ingest.main(["--limit", "5"])` raises `SystemExit` (argparse rejects the unknown flag), asserting it is no longer accepted.

Create `backend/tests/test_cron_schedule.py`:

```python
import croniter


def test_cadence_is_valid_and_daily() -> None:
    from app.ingestion.schedule import SCHEDULE

    base = croniter.croniter(SCHEDULE, start_time=None)
    first = base.get_next()
    second = base.get_next()
    assert (second - first) == 86400  # 24h apart
```

(If `croniter` requires a start time, use `datetime(2026, 1, 1, tzinfo=timezone.utc)` and assert the two returned datetimes are 24h apart.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest backend/tests/test_ingest_cli.py backend/tests/test_cron_schedule.py -v`
Expected: FAIL — `test_cron_schedule.py`: `ModuleNotFoundError: No module named 'croniter'`; `test_ingest_cli.py`: signatures/types fail against the current `run_ingestion(limit)`.

- [ ] **Step 3: Add `croniter` and implement**

Add `"croniter>=1.8"` to `backend/pyproject.toml` `dependencies` and run `make sync`. Create `backend/app/ingestion/schedule.py`. Rewrite `backend/app/ingest.py`: keep `build_source()`; `run_ingestion(*, trigger: str = "manual") -> int` opens the engine, builds `IngestRun`, runs, prints per outcome, returns `exit_code`. Update `Makefile`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest backend/tests/test_ingest_cli.py backend/tests/test_cron_schedule.py -v`
Expected: PASS (all tests).

- [ ] **Step 5: Commit**

```bash
git add backend/pyproject.toml backend/app/ingestion/schedule.py backend/app/ingest.py Makefile backend/tests/test_ingest_cli.py backend/tests/test_cron_schedule.py
git commit -m "feat(pbi6): wire --trigger into the CLI and Makefile; add SCHEDULE constant"
```

---

### Task 12: Postgres-gated advisory-lock mutex (opt-in) and docs

**Files:**
- Create: `backend/tests/test_locking_postgres.py`
- Modify: `README.md` (crontab line + gotchas; derived from `SCHEDULE`)
- Test: `backend/tests/test_locking_postgres.py` (new, `ingest` marker)

**Interfaces:**
- Consumes: `ingestion_lock` (Task 4), `SCHEDULE` (Task 11).
- Produces: a Postgres mutual-exclusion test proving two concurrent `ingestion_lock` holders cannot both hold; and README documentation that cites `SCHEDULE` as the source of truth.

- [ ] **Step 1: Write the Postgres mutex test**

Create `backend/tests/test_locking_postgres.py`, model after `test_migration_0003.py` (module-level `pytestmark = pytest.mark.ingest`, `DATABASE_URL` from env). Two sessions on real Postgres: the first `with ingestion_lock(s1) as held1:` must yield `True`; while held, a second `with ingestion_lock(s2) as held2:` must yield `False`. On exit, `held1`'s release (via the `finally`) lets a subsequent acquisition succeed. Query with raw `text("SELECT ...")`, and clean up in `finally`.

- [ ] **Step 2: Verify it is deselected by `make test`**

Run: `uv run pytest -m "not ingest" -q`
Expected: PASS (all default tests pass; `test_locking_postgres.py` collected but skipped as non-selected).

- [ ] **Step 3: Update `README.md`**

Add the documented crontab line (derived from `SCHEDULE`):

```
17 6 * * * cd /home/jason/job-search && /usr/bin/make ingest TRIGGER=cron >> /var/log/jobsearch-ingest.log 2>&1
```

and the gotchas (absolute paths; Docker daemon up; writable log). State that the DB record covers attempts that reached the app, not launches that never ran. Note the `SCHEDULE` constant in `backend/app/ingestion/schedule.py` is the single source of truth for the `17 6 * * *` value.

- [ ] **Step 4: Commit**

```bash
git add backend/tests/test_locking_postgres.py README.md
git commit -m "test(pbi6): add opt-in postgres advisory-lock mutex test + cron docs"
```

---

### Task 13: Full verification and tracker tick

**Files:**
- Modify: `implementation_checklist/pbi_tracker.md` (tick PBI 6)

**Interfaces:**
- Consumes: all prior tasks.

- [ ] **Step 1: Run lint, typecheck, and the default test suite**

Run:
```bash
make lint
make typecheck
make test
```
Expected: all green. (`make lint` covers ruff check + format check; `make typecheck` runs mypy strict over `backend/app` and `shared`; `make test` is `pytest -m "not ingest"`.)

- [ ] **Step 2: Run the real-crawl integration test (opt-in, needs network + Postgres)**

Run: `make db-up && make migrate && make test-integration`
Expected: `test_real_crawl_yields_nonempty` passes; the `crawl_runs` migrations apply cleanly against Postgres.

- [ ] **Step 3: Tick PBI 6 in the tracker**

In `implementation_checklist/pbi_tracker.md`, mark the PBI 6 line complete (matching the existing checkbox idiom; do not edit `frontend/src/pages/pbis.ts` — its `title`/`description` for PBI 6 are unchanged by this backend-only PBI).

- [ ] **Step 4: Commit**

```bash
git add implementation_checklist/pbi_tracker.md
git commit -m "docs(pbi6): tick PBI 6 crawl scheduler complete"
```

---

## Self-Review Notes

- **Spec coverage:** §6.1 (robots ratification) → Task 6 (`ROBOTSTXT_OBEY=False`) + Task 7 (guard); §6.2 (rate budgets) → Task 5; §6.3 (settings + §6.3.1 guard) → Task 6 + Task 7; §6.4 (spider) → Task 8; §6.5 (run record) → Task 1 + Task 2 + Task 3; §6.6 (lock) → Task 4 + Task 12; §6.7 (`IngestRun`) → Task 9 + Task 10; §6.8 (CLI/cron) → Task 11 + Task 12; §6.9 (`croniter`) → Task 11.
- **`SCHEDULE` single source of truth** is created in Task 11, but the CLI wiring is what the README (Task 12) reads from — the plan sequences them correctly (11 before 12).
- **`ingestion_lock` postgres branch** is exercised by the opt-in Task 12 test, not the unit suite (so `make test` holds hermetic); the SQLite branch is pinned in Task 4.
