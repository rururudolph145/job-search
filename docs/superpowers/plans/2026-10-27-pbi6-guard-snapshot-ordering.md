# PBI 6 — Policy Guard Snapshot Ordering Fix Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stop `PolicyGuardMiddleware` from raising on every live crawl by taking its permitted-scope snapshot *after* the spider's output generator has started, not before.

**Architecture:** `PolicyGuardMiddleware.process_spider_output` currently builds `allowed` from `spider.allowed_sitemap_urls` *before* entering `async for request in result`. That `result` generator has not run yet, so on a fresh crawl the attribute is still the `set()` that `parse` assigns on entry — the snapshot is empty, and the first job request raises `PolicyViolation`. Because `parse` fully populates the set before its first `yield` (verified: the set goes `0 → 662` across one `next()`), snapshotting on the **first item** yields the complete set. No spider change is required.

**Observed and verified (live, Scrapy 2.19.0):**

| Guard variant | Downloader requests | Job pages fetched (200) | `PolicyViolation` |
|---|---|---|---|
| Current (snapshot before loop) | 2 | 0 | 1 |
| Snapshot on first item | 48 | 24 | 0 |

**Out of scope — do not touch:** items still come out 0 after this fix, because the Tokyo location filter finds no `Tokyo` term in job pages whose data is now client-rendered. That is Gate 3, tracked separately; it is **not** a task here. Sitemap 301 handling, the redirect rule, and `parse` itself are also unchanged.

**Tech Stack:** Python 3.13, Scrapy 2.19.0, pytest, mypy strict, ruff, uv workspace.

**Spec:** [docs/superpowers/specs/2026-10-27-pbi6-crawl-scheduler-design.md](../specs/2026-10-27-pbi6-crawl-scheduler-design.md) (§6.3.1 permitted-scope guard)

## Global Constraints

- Python `>=3.13`; every function/method fully annotated (mypy `disallow_untyped_defs`, `no_implicit_optional`).
- Ruff selects `E, W, F, I, C, B`, double quotes, 88-char lines (`E501` ignored).
- `PolicyGuardMiddleware.process_spider_output` **must remain an async generator** — Scrapy 2.19 raises `TypeError` at registration for a sync hook. `test_registers_with_scrapy_middleware_manager` pins this; do not regress it.
- `backend/tests/conftest.py` provides an `asyncio.run` shim for coroutine tests. Do not add `pytest-asyncio`.
- Permitted scope stays `allowed_sitemap_urls ∪ start_urls ∪ (redirect targets whose `redirected_from` meta names an in-scope URL)`.
- Unit tests must not touch the network. `make test` is `pytest -m "not ingest"`.
- **The snapshot must still be taken exactly once per `process_spider_output` call.** Recomputing per item would let a mid-stream `parse` state leak in and is what the original comment guarded against; Task 1 keeps the single-snapshot property.

## Review Focus

Inputs and conditions the happy path does not exercise, most likely to bite a person running `make ingest`:

- **A spider whose `allowed_sitemap_urls` is empty until the output generator runs.** This is the production shape and the bug being fixed. A test that pre-populates the attribute on the spider instance (as every existing guard test does) cannot catch it. — Task 1.
- **A guard called on a spider with no `allowed_sitemap_urls` attribute at all.** `getattr(..., set())` is the fallback; it must still work after the snapshot moves. — Task 1.
- **An output generator that yields nothing.** The snapshot must never be needed, and `process_spider_output` must not raise or hang on an empty stream. — Task 1.
- **The sitemap response's own pass through the guard** (the exact production path: one call, `allowed` empty at entry, 662 items out). — Task 1.
- **A violation arriving after many permitted requests in one pass.** The single snapshot must still be the complete set, so the late violation is still caught. — Task 1.

---

### Task 1: Snapshot the permitted set on the first output item

**Files:**
- Modify: `backend/app/ingestion/middleware.py:33-58`
- Test: `backend/tests/test_policy_guard.py`

**Interfaces:**
- Consumes: `GoogleCareersSpider.parse` (a sync generator that assigns `self.allowed_sitemap_urls = set()` on entry and fully populates it before its first `yield`), `PolicyGuardMiddleware._is_permitted(request: scrapy.Request, allowed: set[str]) -> bool` (unchanged), `SpiderMiddlewareManager.scrape_response_async`, `get_crawler`.
- Produces: `PolicyGuardMiddleware.process_spider_output(response, result: AsyncIterable[scrapy.Request], spider: scrapy.Spider) -> AsyncIterator[scrapy.Request]` — unchanged signature and return type. Only the internal position of the snapshot moves.

- [x] **Step 1: Write the failing test**

Append to `backend/tests/test_policy_guard.py`. It drives the guard through the real `SpiderMiddlewareManager` with the **production spider**, so `allowed_sitemap_urls` is empty at guard-call time and only populates once `parse` is iterated — the shape the existing tests cannot produce.

```python
async def test_passes_requests_whose_scope_is_populated_during_iteration() -> None:
    """The production shape: the spider fills its scope while the output runs.

    ``GoogleCareersSpider.parse`` assigns a fresh empty set on entry and fills
    it before its first yield. Snapshotting the set before the output generator
    runs therefore snapshots the empty set and rejects every request — the live
    crawl failing after two requests. Exercises the real middleware chain, which
    the pre-populated-FakeSpider tests cannot.
    """
    from app.ingestion.spiders.google_careers import GoogleCareersSpider

    body = (
        '<?xml version="1.0"?>'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
        "".join(
            "<url><loc>https://careers.google.com/jobs/results/"
            f"{i}-software-engineer/</loc></url>"
            for i in range(3)
        )
        + "</urlset>"
    ).encode()
    response = TextResponse(
        "https://www.google.com/about/careers/applications/jobs/sitemap.xml",
        body=body,
        encoding="utf-8",
    )
    spider = GoogleCareersSpider()
    crawler = get_crawler(GoogleCareersSpider)
    crawler.spider = spider
    manager = SpiderMiddlewareManager(PolicyGuardMiddleware(), crawler=crawler)

    async def scrape_func(
        response: scrapy.http.Response, request: scrapy.Request
    ) -> Iterable[scrapy.Request]:
        return spider.parse(response)

    chain = await manager.scrape_response_async(scrape_func, response, None)  # type: ignore[arg-type]
    passed = [r async for r in chain]
    assert [r.url for r in passed] == [
        f"https://careers.google.com/jobs/results/{i}-software-engineer/"
        for i in range(3)
    ]
```

Add `TextResponse` to the existing scrapy imports at the top of the file (it currently imports `scrapy` only): `from scrapy.http import TextResponse`.

- [x] **Step 2: Run test to verify it fails**

Run: `uv run --package jobsearch-backend pytest "backend/tests/test_policy_guard.py::test_passes_requests_whose_scope_is_populated_during_iteration" -v`

Expected: FAIL with `app.ingestion.middleware.PolicyViolation: crawl requested 'https://careers.google.com/jobs/results/0-software-engineer/', which is outside the permitted sitemap scope`.

- [x] **Step 3: Move the snapshot in `process_spider_output`**

In `backend/app/ingestion/middleware.py`, replace the body of `process_spider_output` so `allowed` is built lazily on the first item:

```python
    async def process_spider_output(
        self,
        response: scrapy.http.Response,
        result: AsyncIterable[scrapy.Request],
        spider: scrapy.Spider,
    ) -> AsyncIterator[scrapy.Request]:
        # Snapshot on the first item, not before the loop. ``result`` is the spider
        # callback's unconsumed generator: ``parse`` has not run yet when this method
        # is entered, so a snapshot taken there sees the empty set ``parse`` assigns
        # on entry and rejects every request (the live crawl died after two requests).
        # ``parse`` fills the whole set before its first yield, so the first item is
        # already backed by the complete scope. Taken once, as before, so a scope
        # mutation mid-stream cannot leak into a partially-checked crawl.
        allowed: set[str] | None = None
        async for request in result:
            if allowed is None:
                allowed = set(getattr(spider, "allowed_sitemap_urls", set()))
                allowed.update(spider.start_urls)
            if not self._is_permitted(request, allowed):
                raise PolicyViolation(
                    f"crawl requested {request.url!r}, which is outside the "
                    "permitted sitemap scope"
                )
            yield request
```

Delete the stale comment lines above `allowed` in the current version that say "Snapshot `allowed` before consuming `result`" — that guidance is now inverted and would mislead the next reader.

- [x] **Step 4: Run the full guard test file**

Run: `uv run --package jobsearch-backend pytest backend/tests/test_policy_guard.py -v`

Expected: PASS — the new test plus all existing guard tests, including `test_registers_with_scrapy_middleware_manager` (async registration still holds) and `test_raises_on_late_violation_after_many_permitted` (the single snapshot still catches a late violation).

- [x] **Step 5: Run the full suite**

Run: `make test`

Expected: PASS, no failures.

- [x] **Step 6: Commit**

```bash
git add backend/app/ingestion/middleware.py backend/tests/test_policy_guard.py
git commit -m "fix(pbi6): snapshot permitted scope on first output item, not before iteration"
```

---

### Task 2: Confirm the live crawl gets past the guard

**Files:**
- Test: `backend/tests/test_ingest_integration.py` (existing, no change expected)

**Interfaces:**
- Consumes: `GoogleCareersSource.fetch` via `make test-integration`.
- Produces: nothing. This is the acceptance gate for the guard fix **only** — it does not require items.

- [x] **Step 1: Run the live crawl and count progress past the guard**

Run:

```bash
uv run --package jobsearch-backend python - <<'PY'
import warnings; warnings.filterwarnings("ignore")
from scrapy.settings import Settings
from app.ingestion.sources import google_careers as gc
from app.ingestion.scrapy_settings import build_scrapy_settings
from app.ingestion.spiders.google_careers import SITEMAP_URL

gc._CRAWLED_ITEMS.clear()
values = build_scrapy_settings(verbose=False, source_url=SITEMAP_URL)
values["CLOSESPIDER_TIMEOUT"] = 60
process = gc.CrawlerProcess(Settings(values))
crawler = process.create_crawler(gc.GoogleCareersSpider)
process.crawl(crawler)
process.start()
st = crawler.stats.get_stats()
print("requests:", st.get("downloader/request_count"))
print("200s:", st.get("downloader/response_status_count/200"))
print("policy violations:", st.get("spider_exceptions/PolicyViolation", 0))
PY
```

Expected: `requests` well above 2 (≈40–50 in 60 s at the 2 s delay), `200s` above 10, `policy violations: 0`. This is the measurement that separates a fixed guard from a broken one; 2 requests and 1 violation means the fix is not in effect.

- [x] **Step 2: Record the outcome in the plan**

**Outcome (2026-10-27):** 25 downloader requests, 12 job pages fetched (200), `PolicyViolation` 0 — measured after the Task 1 fix. Before it: 2 requests, 0 fetched, 1 violation. **Do not** claim items are being ingested — they are not, and Task 2 does not ask them to be.

- [x] **Step 3: No commit**

This task changes no files. It is a gate.

---

## Verification Summary

Run in order:

```bash
make lint
make typecheck
make test
```

All must pass. `make test-integration` remains red (`test_real_crawl_yields_nonempty` asserts non-empty drafts) because of the Tokyo filter — that is Gate 3, explicitly out of scope here, and is expected to stay red until a later plan addresses it. Do not weaken that assertion.

## Follow-on (not this plan)

- **Gate 3 — location extraction.** Job pages render location client-side; `body//text()` no longer carries `Tokyo`. Until this is solved, every crawl records 0 drafts. Needs its own spec: the location field was not found in the page's `AF_initDataCallback` blob in spot checks.
