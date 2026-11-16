# PBI 6 — Policy Guard Ordering Fix Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

> **Status: implemented 2026-10-27 — tasks 1–3 shipped, task 4 (live items) did not pass.**
> The diagnosis in *Architecture* was revised twice during implementation; see
> **Implementation Outcome** at the end of this file. The current fix is
> [2026-10-27-pbi6-guard-snapshot-ordering.md](2026-10-27-pbi6-guard-snapshot-ordering.md).
> The remaining work is Gate 3 (location extraction), not this plan.

**Goal:** Make a live `google_careers` crawl reach at least one Tokyo SWE item again, by ensuring `PolicyGuardMiddleware` validates requests only after the spider has finished populating the crawl's permitted scope.

**Architecture:** `GoogleCareersSpider.parse` currently yields each sitemap `<loc>` request immediately after adding it to `self.allowed_sitemap_urls`. **Observed and verified:** the permitted set grows *during* iteration (sizes `1, 2, 3` for a three-URL sitemap), so any consumer that inspects it mid-stream sees a partial scope. **Observed and verified on the live site:** the guard raised `PolicyViolation` on the first job request while `allowed_sitemap_urls` was empty, ending the crawl after two requests with zero items. **Not verified:** the exact scheduling mechanism by which the guard resumed before `parse` completed. The fix does not depend on knowing that mechanism — it removes the mid-stream state entirely by collecting the complete permitted set and the full request list before yielding anything.

**Tech Stack:** Python 3.13, Scrapy 2.19.0, pytest, mypy strict, ruff, uv workspace.

**Spec:** [docs/superpowers/specs/2026-10-27-pbi6-crawl-scheduler-design.md](../specs/2026-10-27-pbi6-crawl-scheduler-design.md) (§6.3.1 permitted-scope guard)

## Global Constraints

- Python `>=3.13`; every new function/method fully annotated (mypy `disallow_untyped_defs`, `no_implicit_optional`). `from __future__ import annotations` at the top of every module touched.
- Ruff selects `E, W, F, I, C, B`, double quotes, 88-char lines (`E501` ignored).
- `PolicyGuardMiddleware.process_spider_output` **must remain an async generator** — Scrapy 2.19 raises `TypeError` at registration for a sync hook. A test already pins this; do not regress it.
- `backend/tests/conftest.py` exists and provides an `asyncio.run` shim for coroutine tests. Do not add `pytest-asyncio`.
- The permitted scope is `allowed_sitemap_urls ∪ start_urls ∪ DECLARED_REDIRECT_PREFIXES`. `DECLARED_REDIRECT_PREFIXES` is `("https://www.google.com/about/careers/",)` and stays scoped to that subtree.
- Unit tests must not touch the network. `make test` is `pytest -m "not ingest"`; `make test-integration` is the opt-in live crawl.
- The live site 301s `careers.google.com/*` to `www.google.com/about/careers/applications/*`, and the redirected sitemap yields a job URL on the **original** `careers.google.com` host (redirect re-issues only the sitemap request; job requests are built fresh by `parse`).

## Review Focus

Inputs and conditions the spec's happy path does not exercise, most likely to bite a person running `make ingest`, each paired with the task that pins it.

- **A sitemap whose parse is suspended mid-iteration.** The failure this plan exists to fix: the guard must never observe a request before the crawl's permitted scope is complete. — Task 1.
- **An out-of-scope URL that appears *after* many in-scope ones.** Collect-then-yield must not silently drop the violation or delay it indefinitely; the guard still raises and still stops the crawl. — Task 2.
- **A sitemap yielding zero matching `<loc>`s.** The crawl must finish with zero drafts and no exception — not hang, and not raise from an empty collection. — Task 2.
- **A job URL that redirects to the declared careers prefix.** Must remain permitted after the parse restructure, so the live crawl still completes. — Task 3.
- **A second `parse` invocation (Scrapy may re-parse a meta-refresh or a redirect).** Re-parsing must not leave stale entries in the permitted set from a previous collection. Task 1 assigns a fresh `set()` on entry to guarantee this; it is not separately tested because no spider path re-parses the sitemap today, and the assignment is the whole guard.

---

### Task 1: Collect-then-yield in `GoogleCareersSpider.parse`

**Files:**
- Modify: `backend/app/ingestion/spiders/google_careers.py:52-61`
- Test: `backend/tests/test_google_careers_spider.py` (create)

**Interfaces:**
- Consumes: `ROLE_PATTERN`, `SITEMAP_URL`, `self.allowed_sitemap_urls: set[str]` (all already exist).
- Produces: `GoogleCareersSpider.parse(response: scrapy.http.Response) -> Iterator[scrapy.Request]` — unchanged signature and return type; only the internal ordering changes. The yielded requests still carry `meta={"job_url": url}` and `callback=self.parse_job`.

- [x] **Step 1: Write the failing test**

Create `backend/tests/test_google_careers_spider.py`:

```python
"""Unit tests for GoogleCareersSpider.parse — no network, synthetic sitemap."""

from app.ingestion.spiders.google_careers import GoogleCareersSpider
from scrapy.http import TextResponse

SITEMAP_URL = "https://careers.google.com/jobs/sitemap"
JOB_A = "https://careers.google.com/jobs/results/1-software-engineer/"
JOB_B = "https://careers.google.com/jobs/results/2-senior-software-engineer/"
JOB_C = "https://careers.google.com/jobs/results/3-staff-software-engineer/"


def _sitemap(*urls: str) -> TextResponse:
    locs = "".join(f"<url><loc>{u}</loc></url>" for u in urls)
    body = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
        f"{locs}</urlset>"
    ).encode()
    return TextResponse(SITEMAP_URL, body=body, encoding="utf-8")


def test_permitted_scope_is_complete_before_first_request_is_validated() -> None:
    """The permitted scope is complete before any request is yielded.

    Pins the verified defect: parse() currently grows allowed_sitemap_urls
    while it yields (sizes 1, 2, 3), so a consumer inspecting it mid-stream
    sees a partial scope. The live crawl meanwhile failed with the guard
    observing an empty set.
    """
    spider = GoogleCareersSpider()
    observed: list[tuple[str, int]] = []
    for request in spider.parse(_sitemap(JOB_A, JOB_B, JOB_C)):
        observed.append((request.url, len(spider.allowed_sitemap_urls)))
    assert observed == [(JOB_A, 3), (JOB_B, 3), (JOB_C, 3)]
```

- [x] **Step 2: Run test to verify it fails**

Run: `uv run pytest backend/tests/test_google_careers_spider.py::test_permitted_scope_is_complete_before_first_request_is_validated -v`

Expected: FAIL — observed sizes are `1, 2, 3` instead of `3, 3, 3`.

- [x] **Step 3: Restructure `parse` to collect before yielding**

In `backend/app/ingestion/spiders/google_careers.py`, replace the loop body so the permitted set is fully populated and the request list fully built before any request is yielded:

```python
    def parse(self, response: scrapy.http.Response) -> Iterator[scrapy.Request]:
        # The sitemap uses a default namespace (xmlns), so match element names by
        # local-name() rather than a bare //loc XPath.
        #
        # Collect first, then yield: Scrapy adapts this sync generator into the
        # async middleware chain, which suspends it between items. Yielding as we
        # go let PolicyGuardMiddleware validate a request before its URL was in
        # allowed_sitemap_urls. Building both fully first restores the invariant.
        # Assigned (not updated) so a re-parse cannot inherit stale entries.
        self.allowed_sitemap_urls = set()
        requests: list[scrapy.Request] = []
        for url in response.xpath(".//*[local-name()='loc']/text()").getall():
            url = str(url).strip()
            if ROLE_PATTERN.search(url):
                self.allowed_sitemap_urls.add(url)
                requests.append(
                    scrapy.Request(url, callback=self.parse_job, meta={"job_url": url})
                )
        yield from requests
```

- [x] **Step 4: Run tests to verify they pass**

Run: `uv run pytest backend/tests/test_google_careers_spider.py -v`

Expected: PASS.

- [x] **Step 5: Run the full suite for regressions**

Run: `make test`

Expected: PASS, no failures.

- [x] **Step 6: Commit**

```bash
git add backend/app/ingestion/spiders/google_careers.py backend/tests/test_google_careers_spider.py
git commit -m "fix(pbi6): populate permitted scope before yielding sitemap requests"
```

---

### Task 2: Pin guard behavior for late violations and empty sitemaps

**Files:**
- Test: `backend/tests/test_policy_guard.py`

**Interfaces:**
- Consumes: `PolicyGuardMiddleware.process_spider_output` (async generator), `PolicyViolation`, and the module-level helpers `_as_async` (wraps a sync iterable as an async iterable) and `_collect` (drains an async generator to a list), both already defined in `test_policy_guard.py` at lines 27-35.
- Produces: no production change. These tests pin behavior that Task 1's restructure must not alter.

- [x] **Step 1: Write the failing test**

Append to `backend/tests/test_policy_guard.py`:

```python
async def test_raises_on_late_violation_after_many_permitted() -> None:
    """A long permitted prefix must not defer or swallow a later violation."""
    spider = FakeSpider()
    legit = [f"https://careers.google.com/jobs/results/{i}-software-engineer/" for i in range(20)]
    spider.allowed_sitemap_urls = set(legit)
    mw = PolicyGuardMiddleware()
    requests = [_request(u) for u in legit] + [_request("https://evil.example/x")]
    with pytest.raises(PolicyViolation):
        await _collect(
            mw.process_spider_output(_response(), _as_async(requests), spider)
        )


async def test_empty_sitemap_yields_nothing_without_raising() -> None:
    """Zero matching <loc>s is a clean empty crawl, not an error."""
    spider = FakeSpider()
    spider.allowed_sitemap_urls = set()
    mw = PolicyGuardMiddleware()
    passed = await _collect(
        mw.process_spider_output(_response(), _as_async([]), spider)
    )
    assert passed == []
```

- [x] **Step 2: Run tests to verify they pass immediately**

Run: `uv run pytest backend/tests/test_policy_guard.py -v`

Expected: PASS (both). These are characterization tests for existing correct behavior; they exist so Task 1's restructure cannot regress it. If either fails, stop and report — the guard's contract has already changed.

- [x] **Step 3: Commit**

```bash
git add backend/tests/test_policy_guard.py
git commit -m "test(pbi6): pin guard behavior for late violations and empty sitemaps"
```

---

### Task 3: Verify the declared-redirect path survives the restructure

**Files:**
- Test: `backend/tests/test_google_careers_spider.py`

**Interfaces:**
- Consumes: `GoogleCareersSpider.parse`, `GoogleCareersSpider.parse_job`, `DECLARED_REDIRECT_PREFIXES`, `PolicyGuardMiddleware`.
- Produces: no production change. Confirms the end-to-end sitemap→job path stays legal.

- [x] **Step 1: Write the failing test**

Append to `backend/tests/test_google_careers_spider.py`:

```python
async def test_job_redirect_target_is_permitted_after_restructure() -> None:
    """careers.google.com jobs 301 to the declared careers prefix; must stay legal."""
    from app.ingestion.middleware import PolicyGuardMiddleware

    spider = GoogleCareersSpider()
    requests = list(spider.parse(_sitemap(JOB_A)))

    redirect_target = JOB_A.replace(
        "careers.google.com", "www.google.com/about/careers/applications"
    )
    redirected = requests[0].replace(url=redirect_target)

    async def stream():
        yield redirected

    passed = [
        r
        async for r in PolicyGuardMiddleware().process_spider_output(
            _sitemap(JOB_A), stream(), spider
        )
    ]
    assert [r.url for r in passed] == [redirect_target]
```

- [x] **Step 2: Run test to verify it passes**

Run: `uv run pytest backend/tests/test_google_careers_spider.py::test_job_redirect_target_is_permitted_after_restructure -v`

Expected: PASS. If FAIL with `PolicyViolation`, the restructure broke scope population.

- [x] **Step 3: Commit**

```bash
git add backend/tests/test_google_careers_spider.py
git commit -m "test(pbi6): pin sitemap-to-job redirect path after parse restructure"
```

---

### Task 4: Confirm the live crawl yields items

**Files:**
- Test: `backend/tests/test_ingest_integration.py` (existing, no change expected)

**Interfaces:**
- Consumes: `make_google_careers_source`, `GoogleCareersSource.fetch`.
- Produces: nothing. This is the acceptance gate for the whole plan.

- [x] **Step 1: Run the opt-in live test**

Run: `make test-integration`

Expected: PASS, `1 passed` (plus the 5 other integration tests). `test_real_crawl_yields_nonempty` asserts `drafts` is non-empty.

- [x] **Step 2: If it still returns zero drafts**

Do **not** change the assertion. Capture a single capped diagnostic run and report the stats rather than iterating on the live site:

```bash
uv run python - <<'PY'
from scrapy.settings import Settings
from app.ingestion.sources import google_careers as gc
from app.ingestion.scrapy_settings import build_scrapy_settings
from app.ingestion.spiders.google_careers import SITEMAP_URL, GoogleCareersSpider

gc._CRAWLED_ITEMS.clear()
values = build_scrapy_settings(verbose=False, source_url=SITEMAP_URL)
values["CLOSESPIDER_TIMEOUT"] = 25
process = gc.CrawlerProcess(Settings(values))
crawler = process.create_crawler(GoogleCareersSpider)
process.crawl(crawler)
process.start()
st = crawler.stats.get_stats()
print("items:", len(gc._CRAWLED_ITEMS))
for k in sorted(st):
    if any(t in k for t in ("item_scraped", "spider_exceptions", "response_status", "request_count", "finish_reason")):
        print(f"  {k}={st[k]}")
PY
```

If `spider_exceptions/PolicyViolation` is absent but `item_scraped_count` is 0, the remaining cause is the Tokyo location filter in `parse_job` (a data/rendering question), not the guard. Report that distinction explicitly; do not silently widen `TOKYO_TERMS`.

- [x] **Step 3: Record the outcome**

This task is a gate; it commits nothing. Report to the human partner whether the live crawl passed, and if not, which of the two conditions from Step 2 applies. Do not proceed to a "fix" without that report.

---

## Verification Summary

Run in order; all must pass before the branch is considered done:

```bash
make lint
make typecheck
make test
make test-integration
```

---

## Implementation Outcome (2026-10-27)

Tasks 1–3 shipped; Task 4 (live items) **did not pass**. The plan's diagnosis was revised
twice during implementation, and one defect it did not anticipate surfaced. Validated for
this record on 2026-10-27: `make lint` clean, `make typecheck` clean (37 files),
`make test` → **114 passed, 2 skipped, 6 deselected**.

### What shipped

| Commit | Task | What it did |
|---|---|---|
| `90d8a55` | 1 | `parse` collects the permitted set and the request list before its first yield |
| `020b5f5` | 2 | Characterization tests: late violation still raises, empty sitemap is a clean empty crawl |
| `b5db6c5` | 3 | Pins the sitemap→job redirect path after the restructure |

### Diagnosis revisions (each supersedes the previous)

1. **Plan as written** — "the permitted set grows mid-iteration." Task 1 made `parse`
   collect-then-yield. Live result: still 0 items.
2. **`dcf395b`** — the actual defect was in the guard, not the spider: `process_spider_output`
   snapshotted `allowed` *before* consuming `result`, so it captured the empty `set()` that
   `parse` assigns on entry. Moved the snapshot to the first output item. Live: guard stopped
   raising (2 requests / 1 violation → 25 requests / 12 job pages 200 / 0 violations).
   Full analysis: [snapshot-ordering plan](2026-10-27-pbi6-guard-snapshot-ordering.md).
3. **`5f10d89`, `d2601e4`** — redirect targets were admitted by `www.google.com/about/careers/`
   *prefix*, which let any careers-subtree URL through and contradicted spec §6.1's
   `<loc>`-only scope. Now permitted only when `redirected_from` meta names an in-scope URL.
   `DECLARED_REDIRECT_PREFIXES` is gone; the plan's Global Constraints line naming it is stale.
4. **`0845702`** — defect the plan never considered: `parse_job` yields plain **items**
   (dicts), and Scrapy routes every spider-output item through `process_spider_output`.
   Reading `item.url` raised `AttributeError`, which Scrapy downgraded to a spider error, so
   the crawl reported success with **zero items**. Items now pass through unchecked; only
   `scrapy.Request`s are scope-checked.

### Verification status

- **Gate 1 (`make lint`) + Gate 2 (`make typecheck`): green.**
- **Unit tests: green** — 114 passed, 2 skipped (both pre-existing superseded tests), 6 deselected.
- **Live guard behavior: verified** on 2026-10-27 — 25 requests, 12 job pages 200, 0 `PolicyViolation`.
- **Task 4 / `make test-integration`: still red, by design.** `test_real_crawl_yields_nonempty`
  asserts non-empty drafts and gets none. Do not weaken it.
- **Not re-run on this branch:** the live `make test-integration` acceptance gate after the final
  commits. `experiment_scrapy/jobs.jsonl` (16 Tokyo SWE dicts, dated 2026-10-13, untracked,
  missing the current `external_job_id` field) is **not** evidence for this branch — it
  predates it.

### Why 0 items — Gate 3 (next)

Job pages render location client-side; `body//text()` no longer carries `Tokyo`, so `parse_job`'s
Tokyo filter drops every page. Spot checks did not find the location in the page's
`AF_initDataCallback` blob either. Needs its own spec; affects guard plan's Task 2 Step 2 and
this plan's "Follow-on" section both.

### Cleanup left over

- This plan and the snapshot-ordering plan are untracked; the checkboxes above were ticked
  retroactively on 2026-10-27, not during implementation.
- `docs/superpowers/specs/2026-10-27-pbi6-crawl-scheduler-design.md` is untracked.
- `experiment_scrapy/jobs.jsonl` is untracked scratch output.
- `PolicyGuardMiddleware.process_spider_output` still takes the `spider` argument, which
  Scrapy 2.19 deprecates (warns at registration). Not blocking; migrate to
  `from_crawler` + `crawler.spider` before a Scrapy upgrade.
