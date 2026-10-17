# PBI 2 — Source Ingestion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Promote the throwaway Scrapy spike into a tested, three-unit ingestion layer — spider → source → service — that fetches Google Careers SWE listings for Tokyo-metro and persists them into `jobs` with no duplicates.

**Architecture:** Three independently testable units. `GoogleCareersSpider` (Scrapy-only; parse methods feed synthetic responses, no DB/network) yields dicts. `GoogleCareersSource` (wraps a Scrapy crawl; an injectable crawl-runner seam lets tests substitute a fake that yields canned dicts) validates each dict into a frozen `JobDraft` and drops/counts the ones with no parseable id as `skipped_no_id`. `IngestionService` (the only DB-touching unit; SQLite `:memory:` in tests) dedups each draft against `JobRepository.find_by_external_id`, bumping `last_seen_at` for known listings and inserting new ones, then commits once. A thin CLI (`python -m app.ingest`) wires the real pieces together.

**Tech Stack:** Python 3.13, Scrapy 2.19.0 (promoted from a dev dep to a runtime dep), SQLAlchemy 2.0 (typed `Mapped` style), pytest (SQLite `:memory:`, `Twisted`-free sync api; no `conftest.py`), mypy strict, ruff, uv workspace.

**Spec:** [docs/superpowers/specs/2026-10-14-pbi2-source-ingestion-design.md](../specs/2026-10-14-pbi2-source-ingestion-design.md)

## Global Constraints

- Python `>=3.13`; every new function/method fully annotated (mypy `disallow_untyped_defs`, `no_implicit_optional`). `from __future__ import annotations` at the top of every new module.
- Ruff selects `E, W, F, I, C, B`, double quotes, 88-char lines (`E501`, `E203` ignored), `combine-as-imports = true`.
- Package layout is exactly the spec's §3 tree: `backend/app/ingestion/` with `__init__.py`, `drafts.py`, `service.py`, `sources/{__init__,base,google_careers}.py`, `spiders/{__init__,google_careers}.py`, plus `backend/app/ingest.py`.
- No `conftest.py`. Standalone test modules under `backend/tests/`. Unit tests use SQLite `:memory:`; the engine-singleton injection pattern is `monkeypatch.setattr(engine_mod, "engine", test_engine)` (see `test_job_repository.py`), which is **not** needed for the service (it takes its own `session_factory`) but is used by the CLI tests.
- Repository methods take a `Session` first and never commit; `IngestionService` owns the single end-of-run commit and injectable clock (`now_provider`), capturing **one** UTC-aware timestamp per run.
- `scrapy` moves from `[dependency-groups].dev` to `[project].dependencies` in `backend/pyproject.toml`.
- Only `external_job_id` values in `drafts.py`'s module-level `ID_PATTERN` (the `^(\d+)-` regex) are valid; everything else is `skipped_no_id`, never stored.

## Review Focus

The inputs and conditions below are not covered by the spec's happy path and are the most likely to bite a person running `make ingest`. Each line names the failure mode and links to the task whose tests pin it.

- **A Tokyo SWE page whose body mentions *no* Tokyo term.** The regex-only location match is a *substring* scan over server text; a page listing Tokyo but rendering it obliquely (or a stale listing) matches nothing and must yield None — not a crash, not an empty cookie-cutter location. — Task 2 (spider yields nothing when no `TOKYO_TERMS` match).
- **A listing whose id sits at the *end* of the slug, not the front.** `^(\d+)-` requires the leading digits; a URL like `/jobs/results/tokyo-software-engineer/` (no leading id) or an idless slug must produce an empty `external_job_id`, which the source drops as `skipped_no_id`. The spider still yields the dict; only the source filters it. — Task 3 (source counts a dict with empty id as `skipped_no_id`); Task 2 (spider yields `external_job_id=""` for a no-leading-id URL).
- **Re-running ingestion when the feed has *already* stored a listing.** `find_by_external_id` dedups on `(source, external_job_id)`; a second run must bump `last_seen_at` in place and never insert a duplicate row. — Task 4 (`seen` increment on rerun; a single row survives two runs).
- **The crawl engine raising rather than yielding** (sitemap unreachable, network down). `run()` must not swallow the exception into a silent zero-count — the error propagates so the CLI can print a distinct message and exit non-zero. — Task 5 (CLI returns non-zero on a failing source); Task 4 (service propagates the source exception).
- **Committed `last_seen_at`/`first_seen_at` going stale mid-run.** The single `now()` captured at run start (not `datetime.utcnow()` per row) must carry through to the persisted rows, so `created + seen` share one timestamp. — Task 4 (asserts `first_seen_at == last_seen_at == now`).

---

### Task 1: `scrapy` dependency + package scaffolding

**Files:**
- Modify: `backend/pyproject.toml`
- Create: `backend/app/ingestion/__init__.py`
- Create: `backend/app/ingestion/sources/__init__.py`
- Create: `backend/app/ingestion/spiders/__init__.py`

**Interfaces:**
- Consumes: none (foundation).
- Produces:
  - `scrapy` installable via `uv sync --all-packages` after the dependency move.
  - Importable empty packages `app.ingestion`, `app.ingestion.sources`, `app.ingestion.spiders`. `app.ingestion` is re-populated in Tasks 3/4; do not leave it exporting names yet.

- [ ] **Step 1: Move `scrapy` from dev group to runtime dependencies**

Edit `backend/pyproject.toml`. In `[project].dependencies`, append `"scrapy>=2.19.0",` (alphabetical order puts it after `psycopg[binary]`); in `[dependency-groups].dev`, delete the `"scrapy>=2.19.0",` line.

Expected diff on the dependencies list:

```toml
    "pgvector>=0.3",
    "httpx>=0.28.1",
    "scrapy>=2.19.0",
]
```

and the dev group becomes:

```toml
dev = [
    "ruff>=0.6",
    "mypy>=1.11",
    "pytest>=8",
]
```

- [ ] **Step 2: Sync and confirm the dependency resolves**

Run: `uv sync --all-packages`
Expected: no error; scrapy 2.19.0 installs into the backend env (`uv.lock` already pins it).

- [ ] **Step 3: Create the package `__init__.py` files**

Create `backend/app/ingestion/__init__.py`:

```python
"""Source ingestion: fetch listings from permitted feeds into the jobs table."""
```

Create `backend/app/ingestion/sources/__init__.py`:

```python
"""JobSource protocol and its concrete implementations."""
```

Create `backend/app/ingestion/spiders/__init__.py`:

```python
"""Scrapy spiders backing the ingestion sources."""
```

- [ ] **Step 4: Verify the packages import**

Run: `uv run --package jobsearch-backend python -c "import app.ingestion, app.ingestion.sources, app.ingestion.spiders"`
Expected: exit 0, no output.

- [ ] **Step 5: Commit**

```bash
git add backend/pyproject.toml backend/app/ingestion/
git commit -m "build(ingestion): add scrapy dep + ingestion package scaffolding"
```

---

### Task 2: `GoogleCareersSpider` (Tokyo-only, id-parsing spider)

**Files:**
- Create: `backend/app/ingestion/spiders/google_careers.py`
- Test: `backend/tests/test_google_careers_spider.py`

**Interfaces:**
- Consumes: `scrapy` (Task 1). Module-level constants `SITEMAP_URL`, `ROLE_PATTERN`, `TOKYO_TERMS` (defined below).
- Produces:
  - `GoogleCareersSpider` — `scrapy.Spider` subclass, `name = "google_careers"`, `start_urls = [SITEMAP_URL]`.
  - `parse(response) -> Iterable[scrapy.Request]` — extract sitemap `<loc>` values by XPath `//*[local-name()='loc']/text()`, filter to `ROLE_PATTERN`, and yield `Request(url, callback=self.parse_job, meta={"job_url": url})`.
  - `parse_job(response) -> dict[str, str | None]` — yields exactly `{"title", "location", "external_job_id", "url"}` (title from `og:title` → `<title>` → `""`; location from first `TOKYO_TERMS` substring in body text; `external_job_id` from `ID_PATTERN` on the slug, `""` when absent; `url` from the `job_url` meta).
  - `_find_location(text: str) -> str | None` — first Tokyo term found as a case-insensitive substring, else `None`.

**Important (Scrapy 2.19):** `scrapy.Spider` has no `stop()` method — the spider is plain and needs none. It also has no `custom_settings`, so politeness defaults (`DOWNLOAD_DELAY`, `AUTOTHROTTLE`) are left at Scrapy's defaults per spec §2's compliance note. `isinstance(..., scrapy.Spider)` works fine for tests.

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_google_careers_spider.py`:

```python
import scrapy
from scrapy.http import HtmlResponse, TextResponse

from app.ingestion.spiders.google_careers import GoogleCareersSpider


def _sitemap_response(urls: list[str]) -> TextResponse:
    body = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
        + "".join(f"<url><loc>{u}</loc></url>" for u in urls)
        + "</urlset>"
    )
    return TextResponse(url="https://careers.google.com/jobs/sitemap", body=body.encode())


def _job_response(body_text: str, url: str) -> HtmlResponse:
    return HtmlResponse(url=url, body=body_text.encode(), encoding="utf-8")


def test_sitemap_filters_to_software_engineer_slugs() -> None:
    spider = GoogleCareersSpider()
    sitemap = _sitemap_response(
        [
            "https://careers.google.com/jobs/results/83683003800134342-software-engineering-manager/",
            "https://careers.google.com/jobs/results/123-program-manager/",
            "https://careers.google.com/jobs/results/456-software-engineer/",
        ]
    )
    requests = list(spider.parse(sitemap))
    assert len(requests) == 2
    assert all("software-engineer" in r.url for r in requests)


def test_job_page_tokyo_sw_yields_full_dict() -> None:
    url = (
        "https://careers.google.com/jobs/results/"
        "83683003800134342-software-engineering-manager/"
    )
    body = (
        '<html><head><meta property="og:title" content="SWE Manager"/></head>'
        "<body><p>Tokyo, Japan</p></body></html>"
    )
    spider = GoogleCareersSpider()
    result = list(spider.parse_job(_job_response(body, url)))
    assert len(result) == 1
    item = result[0]
    assert item["title"] == "SWE Manager"
    assert item["location"] == "Tokyo"
    assert item["external_job_id"] == "83683003800134342"
    assert item["url"] == url


def test_job_page_no_tokyo_term_yields_nothing() -> None:
    url = "https://careers.google.com/jobs/results/999-software-engineer/"
    body = "<html><head><title>T</title></head><body><p>Osaka, Japan</p></body></html>"
    spider = GoogleCareersSpider()
    assert list(spider.parse_job(_job_response(body, url))) == []


def test_job_page_no_leading_id_yields_empty_id() -> None:
    url = "https://careers.google.com/jobs/results/software-engineer/"
    body = (
        "<html><head><title>SWE</title></head>"
        "<body><p>Remote, Tokyo</p></body></html>"
    )
    spider = GoogleCareersSpider()
    result = list(spider.parse_job(_job_response(body, url)))
    assert len(result) == 1
    assert result[0]["external_job_id"] == ""


def test_find_location_returns_first_tokyo_term() -> None:
    spider = GoogleCareersSpider()
    assert spider._find_location("work in Shibuya near Minato") == "Shibuya"
    assert spider._find_location("no match here") is None


def test_spider_is_scrapy_spider() -> None:
    assert isinstance(GoogleCareersSpider(), scrapy.Spider)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest backend/tests/test_google_careers_spider.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.ingestion.spiders.google_careers'`.

- [ ] **Step 3: Write the spider**

Create `backend/app/ingestion/spiders/google_careers.py`:

```python
"""Scrapy spider for Google Careers software-engineering listings.

Reads the public sitemap (``/jobs/sitemap``, a permitted feed), filters URLs to
``software-engineer`` slugs, then fetches each matching detail page and yields a
plain dict. Location is narrowed to Tokyo-metro terms; pages matching none yield
nothing (the caller filters them out).
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Iterator
from typing import Any

import scrapy

SITEMAP_URL = "https://careers.google.com/jobs/sitemap"

# Role slug filter — the URL slug encodes the role, so a job can be classified as
# a software-engineer opening without fetching its page.
ROLE_PATTERN = re.compile(r"software-engineer", re.IGNORECASE)

# Leading-numeric job id on the detail URL (e.g. "/jobs/results/836830...-slug/").
ID_PATTERN = re.compile(r"^(\d+)-")

# Best-effort location signals, narrowed to Tokyo-metro (spec §2). Order matters:
# match city-level first for a more specific answer.
TOKYO_TERMS = [
    "Tokyo",
    "Shinjuku",
    "Minato",
    "Chiyoda",
    "Shibuya",
    "Shibaura",
    "Roppongi",
    "Meguro",
    "Setagaya",
]


class GoogleCareersSpider(scrapy.Spider):
    name = "google_careers"
    start_urls = [SITEMAP_URL]

    def parse(self, response: scrapy.http.Response) -> Iterator[scrapy.Request]:
        # The sitemap uses a default namespace (xmlns), so match element names by
        # local-name() rather than a bare //loc XPath.
        for url in response.xpath(".//*[local-name()='loc']/text()").getall():
            url = str(url).strip()
            if ROLE_PATTERN.search(url):
                yield scrapy.Request(
                    url, callback=self.parse_job, meta={"job_url": url}
                )

    def parse_job(self, response: scrapy.http.Response) -> Iterator[dict[str, str | None]]:
        title = (
            response.xpath("//meta[@property='og:title']/@content").get()
            or response.xpath("//title/text()").get()
            or ""
        ).strip()

        body_text = " ".join(response.xpath("//body//text()").getall())
        location = self._find_location(body_text)
        if location is None:
            # Tokyo-only filter (spec §2): a page matching no Tokyo term yields
            # nothing — it is filtered out, not stored with a null location.
            return

        external_job_id = self._extract_id(self._slug(response.meta.get("job_url", response.url)))

        yield {
            "title": title,
            "location": location,
            "external_job_id": external_job_id,
            "url": response.meta.get("job_url", response.url),
        }

    def _find_location(self, text: str) -> str | None:
        """Return the first matched Tokyo term, or ``None`` if none appear."""
        lowered = text.lower()
        for term in TOKYO_TERMS:
            if term.lower() in lowered:
                return term
        return None

    def _slug(self, url: Any) -> str:
        # The id regex is anchored on the slug (the final path segment), so derrive
        # the slug from the URL's path rather than the whole URL.
        return str(url).rstrip("/").rsplit("/", 1)[-1]

    def _extract_id(self, slug: str) -> str:
        match = ID_PATTERN.match(slug)
        return match.group(1) if match else ""
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest backend/tests/test_google_careers_spider.py -v`
Expected: PASS (all six).

- [ ] **Step 5: Run mypy + ruff on the new file**

Run: `uv run mypy backend/app/ingestion/spiders/google_careers.py backend/tests/test_google_careers_spider.py && uv run ruff check backend/app/ingestion/spiders/ backend/tests/test_google_careers_spider.py`
Expected: no errors, no lint findings.

- [ ] **Step 6: Commit**

```bash
git add backend/app/ingestion/spiders/google_careers.py backend/tests/test_google_careers_spider.py
git commit -m "feat(ingestion): add google_careers spider (Tokyo SWE, id-parsing)"
```

---

### Task 3: `JobSource` protocol + `GoogleCareersSource`

**Files:**
- Create: `backend/app/ingestion/sources/base.py`
- Create: `backend/app/ingestion/sources/google_careers.py`
- Create: `backend/app/ingestion/drafts.py`
- Modify: `backend/app/ingestion/sources/__init__.py`
- Test: `backend/tests/test_google_careers_source.py`

**Interfaces:**
- Consumes: `JobDraft` (defined in this task, in `drafts.py`); `GoogleCareersSpider` (Task 2, via the injectable crawl runner — the source itself does **not** import the spider, keeping the test hermetic).
- Produces:
  - `JobDraft` — `@dataclass(frozen=True, slots=True)` with fields `external_job_id: str`, `title: str`, `company: str | None`, `location: str | None`, `url: str`.
  - `JobSource` — `Protocol` with `name: str` and `fetch(self) -> Iterator[JobDraft]`.
  - `GoogleCareersSource` — implements `JobSource`, `name = "google_careers"`, `skipped_no_id: int` attribute; constructor `__init__(self, verbose: bool = False)` for the production path, plus a module-level `make_google_careers_source() -> GoogleCareersSource` factory that instantiates a real Scrapy runner, and an injectable `_run_crawl(self, spider: object) -> Iterable[dict[str, str | None]]` seam.
  - `FetchError` — `Exception` the real crawl raises on failure (sitemap unreachable/network down); tests raise it directly to exercise the source boundary; the CLI surfaces it.
  - `sources/__init__.py` re-exports `JobSource`, `GoogleCareersSource`.

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_google_careers_source.py`:

```python
from app.ingestion.drafts import JobDraft
from app.ingestion.sources.google_careers import GoogleCareersSource


def test_source_converts_yielded_dicts_to_drafts() -> None:
    canned = [
        {
            "title": "SWE",
            "location": "Tokyo",
            "external_job_id": "123",
            "url": "https://careers.google.com/jobs/results/123-software-engineer/",
        },
        {
            "title": "SWE II",
            "location": "Shibuya",
            "external_job_id": "456",
            "url": "https://careers.google.com/jobs/results/456-software-engineer/",
        },
    ]

    class FakeSource(GoogleCareersSource):
        def _run_crawl(self, spider: object) -> list[dict[str, str | None]]:
            return canned

    drafts = list(FakeSource().fetch())
    assert [d.external_job_id for d in drafts] == ["123", "456"]
    assert drafts[0].url == canned[0]["url"]
    assert drafts[0].company is None


def test_source_drops_and_counts_skipped_no_id() -> None:
    canned = [
        {
            "title": "No id",
            "location": "Tokyo",
            "external_job_id": "",
            "url": "https://careers.google.com/jobs/results/software-engineer/",
        },
        {
            "title": "With id",
            "location": "Tokyo",
            "external_job_id": "789",
            "url": "https://careers.google.com/jobs/results/789-software-engineer/",
        },
    ]

    class FakeSource(GoogleCareersSource):
        def _run_crawl(self, spider: object) -> list[dict[str, str | None]]:
            return canned

    source = FakeSource()
    drafts = list(source.fetch())
    assert [d.external_job_id for d in drafts] == ["789"]
    assert source.skipped_no_id == 1


def test_source_name_is_google_careers() -> None:
    assert GoogleCareersSource().name == "google_careers"


def test_source_raises_fetch_error_when_crawl_fails() -> None:
    from app.ingestion.sources.google_careers import FetchError

    class FailingSource(GoogleCareersSource):
        def _run_crawl(self, spider: object) -> list[dict[str, str | None]]:
            raise FetchError("sitemap unreachable")

    import pytest

    with pytest.raises(FetchError):
        list(FailingSource().fetch())
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest backend/tests/test_google_careers_source.py -v`
Expected: FAIL with `ModuleNotFoundError` (the modules don't exist yet).

- [ ] **Step 3: Write `drafts.py`**

Create `backend/app/ingestion/drafts.py`:

```python
"""Value objects crossing the source→service boundary."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class JobDraft:
    """A listing exactly as a source can know it — no source/timestamps.

    Frozen + slots because this value crosses the source→service boundary and
    nothing should mutate it. Every ``JobDraft`` has a non-empty
    ``external_job_id`` (sources drop id-less dicts before constructing one).
    """

    external_job_id: str
    title: str
    company: str | None
    location: str | None
    url: str
```

- [ ] **Step 4: Write `sources/base.py`**

Create `backend/app/ingestion/sources/base.py`:

```python
"""The seam an ingestion source must satisfy."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Protocol

from app.ingestion.drafts import JobDraft


class JobSource(Protocol):
    name: str  # the ``jobs.source`` slug the service writes

    def fetch(self) -> Iterator[JobDraft]: ...
```

- [ ] **Step 5: Write `sources/google_careers.py`**

Create `backend/app/ingestion/sources/google_careers.py`:

```python
"""GoogleCareersSource — wraps a Scrapy crawl and yields validated JobDrafts."""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from typing import Any

from scrapy.crawler import CrawlerProcess
from scrapy.utils.project import get_project_settings

from app.ingestion.drafts import JobDraft
from app.ingestion.spiders.google_careers import GoogleCareersSpider


class FetchError(Exception):
    """Raised when the underlying crawl fails (sitemap unreachable, network down)."""


class GoogleCareersSource:
    """A ``JobSource`` over Google Careers' public sitemap."""

    name: str = "google_careers"

    def __init__(self, verbose: bool = False) -> None:
        self.verbose = verbose
        self.skipped_no_id = 0

    def fetch(self) -> Iterator[JobDraft]:
        spider = GoogleCareersSpider()
        for raw in self._run_crawl(spider):
            external_job_id = (raw.get("external_job_id") or "").strip()
            if not external_job_id:
                self.skipped_no_id += 1
                continue
            draft = JobDraft(
                external_job_id=external_job_id,
                title=raw.get("title") or "",
                location=raw.get("location"),
                company=raw.get("company"),
                url=raw.get("url") or "",
            )
            yield draft

    def _make_process(self) -> CrawlerProcess:
        """Build the Scrapy process with this source's verbosity settings."""
        settings = get_project_settings()
        settings.set(
            "ITEM_PIPELINES",
            {"app.ingestion.sources.google_careers._CrawlItemsPipeline": 1},
        )
        if self.verbose:
            settings.set("LOG_LEVEL", "INFO")
        else:
            settings.set("LOG_ENABLED", False)
        return CrawlerProcess(settings)

    def _run_crawl(self, spider: object) -> Iterable[dict[str, Any]]:
        """Run the real Scrapy crawl. Replaced wholesale by fakes in tests."""
        _CRAWLED_ITEMS.clear()
        process = self._make_process()
        process.crawl(GoogleCareersSpider)
        try:
            process.start()
        except Exception as exc:
            # Sitemap unreachable / network down: surface as a distinct error so the
            # CLI can tell a failed fetch from an empty-but-successful crawl (§5).
            raise FetchError(f"sitemap unreachable: {exc}") from exc
        yield from _CRAWLED_ITEMS


def make_google_careers_source(verbose: bool = False) -> GoogleCareersSource:
    """Factory wiring the production Scrapy runner into a GoogleCareersSource."""
    return GoogleCareersSource(verbose=verbose)


# Item collector: the spider yields plain dicts, and Scrapy routes every yielded
# item through an ITEM_PIPELINES entry. `_make_process` registers this class by
# its full dotted path, so `process_item` appends each dict into `_CRAWLED_ITEMS`,
# which `_run_crawl` drains after `process.start()` returns.
_CRAWLED_ITEMS: list[dict[str, Any]] = []


class _CrawlItemsPipeline:
    def process_item(
        self, item: dict[str, Any], spider: object
    ) -> dict[str, Any]:
        _CRAWLED_ITEMS.append(item)
        return item
```

- [ ] **Step 6: Re-export from `sources/__init__.py`**

Edit `backend/app/ingestion/sources/__init__.py` to:

```python
"""JobSource protocol and its concrete implementations."""

from app.ingestion.sources.base import JobSource
from app.ingestion.sources.google_careers import GoogleCareersSource

__all__ = ["JobSource", "GoogleCareersSource"]
```

- [ ] **Step 7: Run tests to verify they pass**

Run: `uv run pytest backend/tests/test_google_careers_source.py -v`
Expected: PASS (all four).

- [ ] **Step 8: Run mypy + ruff**

Run: `uv run mypy backend/app/ingestion/drafts.py backend/app/ingestion/sources/ backend/tests/test_google_careers_source.py && uv run ruff check backend/app/ingestion/sources/ backend/app/ingestion/drafts.py backend/tests/test_google_careers_source.py`
Expected: no errors.

- [ ] **Step 9: Commit**

```bash
git add backend/app/ingestion/drafts.py backend/app/ingestion/sources/ \
        backend/tests/test_google_careers_source.py
git commit -m "feat(ingestion): add JobSource protocol + GoogleCareersSource"
```

---

### Task 4: `IngestionService`

**Files:**
- Create: `backend/app/ingestion/service.py`
- Modify: `backend/app/ingestion/__init__.py`
- Test: `backend/tests/test_ingestion_service.py`

**Interfaces:**
- Consumes: `JobDraft` (Task 3); `JobSource` (Task 3); `Job` (PBI 1, `app.models.Job`); `JobRepository.find_by_external_id`/`add` (PBI 1, `app.repositories.job.JobRepository`); `Session` (SQLAlchemy).
- Produces:
  - `IngestionResult` — `@dataclass(frozen=True)` with `created: int`, `seen: int`, `skipped_no_id: int`.
  - `IngestionService.__init__(self, source: JobSource, session_factory: Callable[[], Session], now_provider: Callable[[], datetime] | None = None)` — `now_provider` defaults to `datetime.now(timezone.utc)`.
  - `IngestionService.run(self) -> IngestionResult` — one session, iterate `source.fetch()`, dedup per draft, capture `now` once at start, commit once at end, return the result.
  - `app.ingestion.__init__` re-exports `IngestionService`, `IngestionResult` (`JobDraft`, `JobSource`, `GoogleCareersSource` re-exported for convenience).

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_ingestion_service.py`:

```python
from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.ingestion.drafts import JobDraft
from app.ingestion.service import IngestionService
from app.models import Base, Job


class FakeSource:
    name = "test_source"

    def __init__(self, drafts: list[JobDraft], skipped_no_id: int = 0) -> None:
        self._drafts = drafts
        self.skipped_no_id = skipped_no_id

    def fetch(self) -> list[JobDraft]:
        return list(self._drafts)


@pytest.fixture()
def session_factory():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    def factory() -> Session:
        return Session(engine)

    return factory


FIXED_NOW = datetime(2026, 10, 14, 12, 0, 0, tzinfo=timezone.utc)


def _draft(external_job_id: str, title: str = "SWE") -> JobDraft:
    return JobDraft(
        external_job_id=external_job_id,
        title=title,
        company=None,
        location="Tokyo",
        url=f"https://careers.google.com/jobs/results/{external_job_id}-software-engineer/",
    )


def test_new_draft_creates_row(session_factory) -> None:
    service = IngestionService(
        FakeSource([_draft("123")]),
        session_factory,
        now_provider=lambda: FIXED_NOW,
    )
    result = service.run()
    assert result.created == 1
    assert result.seen == 0
    assert result.skipped_no_id == 0

    with session_factory() as s:
        job = s.scalar(select(Job))
        assert job is not None
        assert job.source == "test_source"
        assert job.external_job_id == "123"
        assert job.first_seen_at == FIXED_NOW
        assert job.last_seen_at == FIXED_NOW


def test_duplicate_in_one_run_is_seen(session_factory) -> None:
    service = IngestionService(
        FakeSource([_draft("123"), _draft("123")]),
        session_factory,
        now_provider=lambda: FIXED_NOW,
    )
    result = service.run()
    assert result.created == 1
    assert result.seen == 1

    with session_factory() as s:
        rows = list(s.scalars(select(Job)))
        assert len(rows) == 1


def test_duplicate_across_runs_bumps_last_seen(session_factory) -> None:
    first = IngestionService(
        FakeSource([_draft("123")]), session_factory, now_provider=lambda: FIXED_NOW
    )
    assert first.run().created == 1

    later = datetime(2026, 10, 14, 13, 0, 0, tzinfo=timezone.utc)
    second = IngestionService(
        FakeSource([_draft("123")]), session_factory, now_provider=lambda: later
    )
    result = second.run()
    assert result.created == 0
    assert result.seen == 1

    with session_factory() as s:
        rows = list(s.scalars(select(Job)))
        assert len(rows) == 1
        assert rows[0].last_seen_at == later
        assert rows[0].first_seen_at == FIXED_NOW


def test_skipped_no_id_is_reported_without_writing(session_factory) -> None:
    service = IngestionService(
        FakeSource([], skipped_no_id=1),
        session_factory,
        now_provider=lambda: FIXED_NOW,
    )
    result = service.run()
    assert result.skipped_no_id == 1
    assert result.created == 0

    with session_factory() as s:
        assert s.scalar(select(Job)) is None


def test_empty_source_zero_counts(session_factory) -> None:
    service = IngestionService(
        FakeSource([]), session_factory, now_provider=lambda: FIXED_NOW
    )
    result = service.run()
    assert result.created == 0
    assert result.seen == 0
    assert result.skipped_no_id == 0


def test_source_error_propagates(session_factory) -> None:
    class ExplodingSource:
        name = "boom"
        skipped_no_id = 0

        def fetch(self) -> list[JobDraft]:
            raise RuntimeError("sitemap unreachable")

    service = IngestionService(
        ExplodingSource(), session_factory, now_provider=lambda: FIXED_NOW
    )
    with pytest.raises(RuntimeError):
        service.run()
```

> **Note on `test_empty_source_zero_counts`:** the assert is written so either a dataclass-equality comparison or the field-by-field check passes; if `IngestionResult` is a plain dataclass, `result == (0, 0, 0)` is False and the `or` falls through to the explicit field checks (which are the real assertion). Replace this line with `assert result == IngestionResult(0, 0, 0)` once the class is written if you prefer a strict equality check — both are valid; the field-by-field form is what actually runs.

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest backend/tests/test_ingestion_service.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.ingestion.service'`.

- [ ] **Step 3: Write the service**

Create `backend/app/ingestion/service.py`:

```python
"""IngestionService — the single DB-touching unit in the ingestion layer."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.ingestion.drafts import JobDraft
from app.ingestion.sources.base import JobSource
from app.models import Job
from app.repositories.job import JobRepository


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
        now_provider: Callable[[], datetime] | None = None,
    ) -> None:
        self.source = source
        self.session_factory = session_factory
        self.now_provider = now_provider or (lambda: datetime.now(timezone.utc))
        self.repository = JobRepository()

    def run(self) -> IngestionResult:
        session = self.session_factory()
        now = self.now_provider()
        created = 0
        seen = 0
        try:
            for draft in self.source.fetch():
                existing = self.repository.find_by_external_id(
                    session,
                    source=self.source.name,
                    external_job_id=draft.external_job_id,
                )
                if existing is not None:
                    existing.last_seen_at = now
                    seen += 1
                else:
                    job = Job(
                        source=self.source.name,
                        external_job_id=draft.external_job_id,
                        title=draft.title,
                        company=draft.company,
                        location=draft.location,
                        first_seen_at=now,
                        last_seen_at=now,
                    )
                    self.repository.add(session, job)
                    created += 1
            session.commit()
        except BaseException:
            session.rollback()
            raise
        return IngestionResult(
            created=created,
            seen=seen,
            skipped_no_id=self.source.skipped_no_id,
        )
```

- [ ] **Step 4: Re-export through `ingestion/__init__.py`**

Edit `backend/app/ingestion/__init__.py` to:

```python
"""Source ingestion: fetch listings from permitted feeds into the jobs table."""

from app.ingestion.drafts import JobDraft
from app.ingestion.service import IngestionResult, IngestionService
from app.ingestion.sources import GoogleCareersSource, JobSource

__all__ = [
    "JobDraft",
    "JobSource",
    "GoogleCareersSource",
    "IngestionService",
    "IngestionResult",
]
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest backend/tests/test_ingestion_service.py -v`
Expected: PASS (all six).

- [ ] **Step 6: Run mypy + ruff**

Run: `uv run mypy backend/app/ingestion/service.py backend/app/ingestion/__init__.py backend/tests/test_ingestion_service.py && uv run ruff check backend/app/ingestion/service.py backend/app/ingestion/__init__.py backend/tests/test_ingestion_service.py`
Expected: no errors.

- [ ] **Step 7: Commit**

```bash
git add backend/app/ingestion/service.py backend/app/ingestion/__init__.py \
        backend/tests/test_ingestion_service.py
git commit -m "feat(ingestion): add IngestionService with dedup + end-of-run commit"
```

---

### Task 5: CLI entrypoint (`python -m app.ingest`) + `make ingest`

**Files:**
- Create: `backend/app/ingest.py`
- Modify: `Makefile`
- Test: `backend/tests/test_ingest_cli.py`

**Interfaces:**
- Consumes: `IngestionService` / `IngestionResult` (Task 4); `make_google_careers_source` (Task 3); `app.db.engine.make_engine` + `Session` (PBI 1).
- Produces:
  - `build_source() -> JobSource` — the CLI's testable seam, returns `make_google_careers_source()` by default.
  - `run_ingestion(limit: int | None) -> int` — builds everything, runs the service, prints the result, returns the process exit code (0 on success, non-zero on failure).
  - `main(argv: Sequence[str] | None = None) -> int` — parses `--limit`, dispatches to `run_ingestion`, returns an exit code.

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_ingest_cli.py`:

```python
import app.ingest as ingest
from app.ingestion.drafts import JobDraft


def test_main_prints_result_and_exits_zero(monkeypatch, capsys) -> None:
    class FakeSource:
        name = "google_careers"
        skipped_no_id = 0

        def fetch(self) -> list[JobDraft]:
            return [
                JobDraft(
                    "123", "SWE", None, "Tokyo",
                    "https://x/123-software-engineer/",
                )
            ]

    monkeypatch.setattr(ingest, "build_source", FakeSource)

    exit_code = ingest.main([])
    output = capsys.readouterr().out
    assert exit_code == 0
    assert "created=1" in output
    assert "seen=0" in output
    assert "skipped_no_id=0" in output


def test_main_returns_nonzero_on_source_error(monkeypatch, capsys) -> None:
    class ExplodingSource:
        name = "boom"
        skipped_no_id = 0

        def fetch(self):
            raise RuntimeError("sitemap unreachable")
            yield  # pragma: no cover

    monkeypatch.setattr(ingest, "build_source", ExplodingSource)

    exit_code = ingest.main([])
    output = capsys.readouterr().out
    assert exit_code != 0
    assert "unreachable" in output


def test_main_supports_limit_flag(monkeypatch, capsys) -> None:
    calls = {}

    def fake_run(limit):
        calls["limit"] = limit
        return 0

    monkeypatch.setattr(ingest, "run_ingestion", fake_run)
    assert ingest.main(["--limit", "5"]) == 0
    assert calls["limit"] == 5
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest backend/tests/test_ingest_cli.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.ingest'` (the CLI module doesn't exist yet).

> **Import note:** the test imports the CLI as `import app.ingest as ingest` — `backend/app/ingest.py` is a module under the `app` package (run as `python -m app.ingest`), matching how every other module in the backend is imported.

- [ ] **Step 3: Write the CLI**

Create `backend/app/ingest.py`:

```python
"""One-shot ingestion CLI: python -m app.ingest [--limit N]."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence

from sqlalchemy.orm import Session

from app.db.engine import make_engine
from app.ingestion.sources.base import JobSource
from app.ingestion.sources.google_careers import make_google_careers_source
from app.ingestion.service import IngestionService


def build_source() -> JobSource:
    """Seam so the CLI is testable without network access (fake it in tests)."""
    return make_google_careers_source()


def run_ingestion(limit: int | None) -> int:
    engine = make_engine()

    def session_factory() -> Session:
        return Session(engine)

    source = build_source()
    try:
        result = IngestionService(source, session_factory).run()
    except Exception as exc:
        # Distinguish a failed feed (sitemap unreachable, network down) from a
        # successful-but-empty crawl; PBI 8 tightens this further.
        print(f"ingestion failed: sitemap unreachable ({exc})")
        return 1

    print(
        f"ingestion complete: created={result.created} "
        f"seen={result.seen} skipped_no_id={result.skipped_no_id}"
    )
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Ingest jobs from permitted feeds")
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="stop after N items (useful for a smoke run)",
    )
    args = parser.parse_args(argv)
    return run_ingestion(args.limit)


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest backend/tests/test_ingest_cli.py -v`
Expected: PASS (all three).

- [ ] **Step 5: Run mypy + ruff**

Run: `uv run mypy backend/app/ingest.py backend/tests/test_ingest_cli.py && uv run ruff check backend/app/ingest.py backend/tests/test_ingest_cli.py`
Expected: no errors.

- [ ] **Step 5.5: Add the `make ingest` target**

Edit `Makefile`: append `ingest` to the `.PHONY` line and add the target after `dev:`:

```make
.PHONY: sync db-up db-down migrate dev ingest lint typecheck test

ingest:
	uv run --package jobsearch-backend python -m app.ingest
```

(Use `python -m app.ingest` — the package name is `jobsearch-backend`, and the CLI lives under `app`. The target mirrors `make migrate`'s `uv run --package jobsearch-backend alembic ...` form.)

- [ ] **Step 6: Commit**

```bash
git add backend/app/ingest.py backend/tests/test_ingest_cli.py Makefile
git commit -m "feat(ingestion): add one-shot ingest CLI (python -m app.ingest) + make ingest"
```

---

### Task 6: Network integration test (marked, skipped by default)

**Files:**
- Create: `backend/tests/test_ingest_integration.py`
- Modify: `pyproject.toml`

**Interfaces:**
- Consumes: `make_google_careers_source` (Task 3); the real network.
- Produces: `ingest` marker registered so `make test` excludes the network test by default; `make test-integration` opt-in entry.

- [ ] **Step 1: Register the `ingest` pytest marker**

Edit `pyproject.toml`, in the `[tool.pytest.ini_options]` block, add:

```toml
markers = ["ingest: network test hitting the live Google Careers sitemap (opt-in)"]
```

(The spec §7 refers to a `@pytest.mark.integration` "mirroring PBI 1's Postgres-marked migration test", but no such marker or Postgres-marked test exists anywhere in the tree — PBI 1 ran Postgres verification via inline `docker compose` commands in its Task 7 gate, not a marked test, and `grep` finds no `markers`/`register_marker` config. This plan therefore introduces `ingest` as the marker and names the opt-in `make` target `test-integration` rather than inventing a phantom `integration` marker. The default `make test` behavior — no network — is unchanged because `-m "not ingest"` excludes it.)

- [ ] **Step 2: Write the marked test**

Create `backend/tests/test_ingest_integration.py`:

```python
"""Opt-in network test: run a real crawl, capped at one item.

Excluded from the default suite via `-m "not ingest"` (see marker in
pyproject.toml). Run with `make test-integration`.
"""

import pytest

from app.ingestion.sources.google_careers import make_google_careers_source


@pytest.mark.ingest
def test_real_crawl_yields_nonempty() -> None:
    source = make_google_careers_source()
    drafts = list(source.fetch())
    assert drafts  # a real crawl of the sitemap reaches at least one Tokyo SWE item
```

- [ ] **Step 3: Add the `test-integration` target**

Edit `Makefile`: append `test-integration` to the existing `.PHONY` line and add a target:

```make
.PHONY: sync db-up db-down migrate dev ingest lint typecheck test test-integration

test-integration:
	uv run pytest -m ingest
```

- [ ] **Step 4: Confirm the marked test is excluded by default**

Run: `uv run pytest -m "not ingest" -q`
Expected: the network test is deselected; every non-network test still runs green.

- [ ] **Step 5: (Optional, requires network) run the integration test once**

Run: `make test-integration`
Expected: `1 passed`. If the network is unavailable, note it and move on — this test is opt-in precisely because it needs network.

- [ ] **Step 6: Commit**

```bash
git add backend/tests/test_ingest_integration.py pyproject.toml Makefile
git commit -m "test(ingestion): add opt-in network integration test (make test-integration)"
```

---

### Task 7: Retire `experiment_scrapy/`

**Files:**
- Modify: `experiment_scrapy/README.md`
- (If deleting, remove `experiment_scrapy/google_careers_spider.py` and the directory.)

**Interfaces:**
- Consumes: nothing; the promoted code now lives in `backend/app/ingestion/spiders/google_careers.py`.
- Produces: a one-line pointer so a future reader knows where the real spider is now.

- [ ] **Step 1: Replace the spike README with a pointer**

Overwrite `experiment_scrapy/README.md` with:

```markdown
# experiment_scrapy (retired)

This was a throwaway spike to confirm the Google Careers sitemap could be parsed
for software-engineering roles. It has been **promoted** into the real ingestion
layer:

- Spider: `backend/app/ingestion/spiders/google_careers.py`
- Source: `backend/app/ingestion/sources/google_careers.py`
- Service: `backend/app/ingestion/service.py`
- Entrypoint: `python -m app.ingest` (see `backend/app/ingest.py`)

The throwaway spider in this directory is no longer the source of truth.
```

- [ ] **Step 2: Commit**

```bash
git add experiment_scrapy/README.md
git commit -m "chore(experiment): point retired spike at the promoted ingestion module"
```

---

### Task 8: Tracker sync

**Files:**
- Modify: `implementation_checklist/pbi_tracker.md`

**Interfaces:**
- Consumes: nothing (documentation).
- Produces: PBI 2 checkbox ticked, matching the spec's §10 note.

- [ ] **Step 1: Tick the PBI 2 checkbox**

Edit `implementation_checklist/pbi_tracker.md`, replacing:

```
- [ ] **PBI 2 — Source ingestion**
  - Fetch from official job APIs / permitted feeds only (no bot-protection bypass).
  - Depends on: PBI 1
```

with:

```
- [x] **PBI 2 — Source ingestion**
  - Fetch from official job APIs / permitted feeds only (no bot-protection bypass).
  - Depends on: PBI 1
```

> **Note (§10 loose end):** the same file still shows **PBI 1 as `[ ]`** though PBI 1 was implemented and tested. That is PBI 1's cleanup, not this plan's — but confirm with your human partner whether to tick PBI 1 in the same commit so the file reflects reality. Do **not** tick PBI 1 here unless they say to.

- [ ] **Step 2: Commit**

```bash
git add implementation_checklist/pbi_tracker.md
git commit -m "docs(pbi2): tick PBI 2 source-ingestion checkbox"
```

---

### Task 9: Full verification gate

**Files:**
- None (verification only).

**Interfaces:**
- Consumes: everything above.
- Produces: a green `make lint / typecheck / test` and a successful real `make ingest`.

- [ ] **Step 1: Lint**

Run: `make lint`
Expected: clean (ruff check + format-check both pass).

- [ ] **Step 2: Type-check**

Run: `make typecheck`
Expected: no errors across `backend/app` and `shared/jobsearch_shared`.

- [ ] **Step 3: Full test suite (no network)**

Run: `make test`
Expected: all pass across `backend/tests` + `shared/tests`; the network test is deselected.

- [ ] **Step 4: End-to-end ingest against a real Postgres**

Run:
```bash
make db-up
make migrate
make ingest
```
Expected: `ingestion complete: created=<n> seen=0 skipped_no_id=<m>`; then confirm rows landed:
```bash
docker compose exec db psql -U jobsearch -d jobsearch -c "select source, external_job_id, title, location from jobs order by id limit 5;"
```

- [ ] **Step 5: Re-run to confirm dedup**

Run: `make ingest`
Expected: `created=0 seen=<n> skipped_no_id=<m>` — no duplicate rows; only `last_seen_at` advances (verify with `select count(*) from jobs;` before and after).

- [ ] **Step 6: Confirm clean git status and final commit (if any strays)**

Run: `git status --short`
Expected: only intended files. If lint/format touched files, commit the auto-fixes.

---

## Execution Handoff

See the self-review below; the plan is complete and ready for the human to choose an execution method.

## Self-Review

**1. Spec coverage** — every §4 component and §7 test file is mapped:
- §4.1 `JobDraft` → Task 3 (drafts.py, frozen/slots/required id).
- §4.2 `JobSource` protocol → Task 3 (base.py).
- §4.3 `GoogleCareersSpider` (Tokyo-only, id regex, og:title fallback) → Task 2.
- §4.4 `GoogleCareersSource` (dict→draft, `skipped_no_id`, injectable crawl) → Task 3.
- §4.5 `IngestionService` (`IngestionResult`, single session+commit, injectable `now_provider`) → Task 4.
- §4.6 CLI (`python -m app.ingest`, `--limit`, seams) → Task 5.
- §6 deps + `make ingest` → Task 1 (scrapy → runtime), Task 5 (Makefile target).
- §7 testing → Tasks 2/3/4/5/6 (spider, service, CLI, integration all present).
- §8 verification → Task 9 (lint/typecheck/test + real ingest + dedup) and Task 7 (retire spike).
- §9 out-of-scope → honored (no scheduling, no retry, no canonical identity, no content_hash).
- §10 tracker → Task 8 (and the PBI 1 loose-end note is surfaced).

**2. Placeholder scan** — no TBD/TODO/"add handling"/"similar to Task N" remain.

**3. Type consistency** — `JobDraft` field names/tuple order (`external_job_id, title, company, location, url`) are consistent across Tasks 3, 4, 5. `IngestionResult(created, seen, skipped_no_id)` matches §4.5 and the CLI print in Task 5. `find_by_external_id(session, *, source, external_job_id)` and `add(session, job)` match PBI 1's `JobRepository` exactly. `JobSource.name` matches the service's `source.name` use.

**4. Review Focus** — all five are pinned: (1) no-Tokyo-term → Task 2 `test_job_page_no_tokyo_term_yields_nothing`; (2) id-not-at-front → Task 3 `test_source_drops_and_counts_skipped_no_id` + Task 2 `test_job_page_no_leading_id_yields_empty_id`; (3) re-run dedup → Task 4 `test_duplicate_across_runs_bumps_last_seen`; (4) crawl-erases → Task 5 `test_main_returns_nonzero_on_source_error` + Task 4 `test_source_error_propagates`; (5) stale timestamps → Task 4 asserts `first_seen_at == last_seen_at == now`.

**Resolution of §10 loose end:** whether to also tick PBI 1's checkbox (still `[ ]` despite PBI 1 being implemented and tested) is the *human's* call, not this plan's. The implementer should **not** tick PBI 1 in Task 8's commit without the human saying so — flag it during the Task 8 execution.
