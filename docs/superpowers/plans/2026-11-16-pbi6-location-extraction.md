# PBI 6 — Location Extraction (Gate 3) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the fragile `body//text()` Tokyo term-scan with structured extraction of the embedded location tuple, storing `country` + `city` on `jobs` so the crawl records Japan SWE jobs again and location becomes a country → city filter dimension.

**Architecture:** The spider's `parse_job` extracts `(city, country)` from the page's embedded data blob (`["Tokyo, Japan",…,"Tokyo","JP"]`), drops pages with no tuple or `country != "JP"`, and yields the values. They flow through `JobDraft` → `IngestionService` (new + re-sight backfill) → the `jobs` table (migration `0005`) → `JobResponse`. The display `location` string is preserved so the API and dashboard keep working unchanged.

**Tech Stack:** Python 3.13, Scrapy 2.19.0, SQLAlchemy 2, Alembic, Pydantic v2 (shared), FastAPI, React + TypeScript, pytest, mypy strict, ruff, uv workspace.

**Spec:** [docs/superpowers/specs/2026-11-16-pbi6-location-extraction-design.md](../specs/2026-11-16-pbi6-location-extraction-design.md)

## Global Constraints

- Python `>=3.13`; every function/method fully annotated (mypy `disallow_untyped_defs`, `no_implicit_optional`); `from __future__ import annotations` at the top of every module touched.
- Ruff selects `E, W, F, I, C, B`, double quotes, 88-char lines (`E501` ignored).
- Location rule: **`country == "JP"`** filters the crawl at the spider. City is extracted for display/future filtering, not for the drop decision.
- **Structured-only, no DOM-text fallback** (spec §6). No tuple → drop. Non-`JP` → drop. No new logging mechanism: drift is observed via `crawl_runs.created=0, seen=0` (spec §7.1).
- `country` and `city` are **nullable** everywhere (old rows null until re-crawl; existing fixtures need not supply them).
- `location` (free-text display) is preserved unchanged.
- Unit tests must not touch the network. `make test` is `pytest -m "not ingest"`; migration tests are Postgres-only, opt-in via the `ingest` marker.
- Title extraction (`og:title`/`<title>`) and `external_job_id` extraction are unchanged.

## Review Focus

Inputs and conditions the happy path does not exercise, most likely to bite a person running `make ingest`:

- **A page whose `city` substring coincides with the display string.** Real tuple is `["Tokyo, Japan",["Tokyo, Japan"],null,null,"Tokyo","JP"]` — a naive regex must capture the *5th/6th* elements (city, country), not the *first* `"Tokyo"`-looking string. — Task 1.
- **A page with no location tuple at all** (format drift). Must drop cleanly (zero items), never raise mid-crawl. — Task 2.
- **A non-Japan page** carrying a valid tuple with `country != "JP"`. Must drop, and never be inserted. — Task 2.
- **An existing row that already exists with `country`/`city` null** (pre-migration data). Re-crawl must backfill it, not leave it null. — Task 4.
- **The `IntegrityError` re-read path** (concurrent/duplicate writer). Backfill must apply there too, not only the happy re-sight path. — Task 4.

---

## Task 1: Extract the location tuple in the spider

**Files:**
- Modify: `backend/app/ingestion/spiders/google_careers.py`
- Test: `backend/tests/test_google_careers_spider.py`

**Interfaces:**
- Consumes: `GoogleCareersSpider.parse_job(response)` (existing), `og:title`/`<title>` extraction (existing), `ID_PATTERN`/`_slug`/`_extract_id` (existing, unchanged).
- Produces: module-level compiled regex `LOCATION_TUPLE` with groups `(display, city, country)`; a helper `GoogleCareersSpider._find_location_tuple(text: str) -> tuple[str, str] | None` returning `(city, country)`; `parse_job` yields dicts containing the new keys `"city": str` and `"country": str` alongside `title`/`location`/`external_job_id`/`url`.

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_google_careers_spider.py`. The fixture body mirrors the verified on-wire shape, including the leading duplicate display string the naive regex must not capture.

```python
_LOC_BLOB = (
    '<html><head><meta property="og:title" content="SWE Manager"/></head>'
    "<body><script>"
    'x("abc","Google","en-US",[["Tokyo, Japan",["Tokyo, Japan"],null,null,"Tokyo","JP"]],'
    'null,[null,"x"])'
    "</script></body></html>"
)


def test_job_page_extracts_city_and_country_from_tuple() -> None:
    url = "https://careers.google.com/jobs/results/83683003800134342-swe/"
    spider = GoogleCareersSpider()
    result = list(spider.parse_job(_job_response(_LOC_BLOB, url)))
    assert len(result) == 1
    item = result[0]
    assert item["city"] == "Tokyo"
    assert item["country"] == "JP"
    assert item["title"] == "SWE Manager"
    assert item["external_job_id"] == "83683003800134342"


def test_find_location_tuple_returns_none_without_tuple() -> None:
    assert GoogleCareersSpider()._find_location_tuple("<p>no blob</p>") is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --package jobsearch-backend pytest "backend/tests/test_google_careers_spider.py::test_job_page_extracts_city_and_country_from_tuple" -v`

Expected: FAIL — `KeyError: 'city'` (the current `parse_job` yields no `city`).

- [ ] **Step 3: Add `LOCATION_TUPLE` and `_find_location_tuple`, use them in `parse_job`**

In `backend/app/ingestion/spiders/google_careers.py`, add near the other module-level patterns a compiled regex matching the tuple shape, capturing display (group 1), city (group 2), country (group 3):

```python
LOCATION_TUPLE = re.compile(
    r'\[\["([^"]*)",\["[^"]*"\],null,null,"([^"]*)","([A-Z]{2}|)"\]\]'
)
```

Add the helper:

```python
def _find_location_tuple(self, text: str) -> tuple[str, str] | None:
    """Return (city, country) from the embedded location tuple, or ``None``."""
    match = LOCATION_TUPLE.search(text)
    if match is None:
        return None
    city, country = match.group(2), match.group(3)
    if not city or not country:
        return None
    return city, country
```

In `parse_job`, replace the body-text location scan with the tuple lookup. If `_find_location_tuple` returns `None`, `return` (drop). Otherwise yield the item with `city`, `country`, and `location` set to the display label. Keep title, `url = self._job_url(response)`, and `external_job_id = self._extract_id(self._slug(url))` as they are. Remove `TOKYO_TERMS` and `_find_location` (superseded). Update the module docstring to describe structured extraction.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run --package jobsearch-backend pytest "backend/tests/test_google_careers_spider.py::test_job_page_extracts_city_and_country_from_tuple" "backend/tests/test_google_careers_spider.py::test_find_location_tuple_returns_none_without_tuple" -v`

Expected: PASS (both).

- [ ] **Step 5: Commit**

```bash
git add backend/app/ingestion/spiders/google_careers.py backend/tests/test_google_careers_spider.py
git commit -m "feat(pbi6): extract country+city from the job page location tuple"
```

---

## Task 2: Drop rules in the spider (no tuple, non-JP) and retire old tests

**Files:**
- Modify: `backend/tests/test_google_careers_spider.py`
- (Production code already handles both drops via Task 1's `parse_job` `return` — the non-`JP` drop is added here.)

**Interfaces:**
- Consumes: `GoogleCareersSpider._find_location_tuple` and the `parse_job` from Task 1.
- Produces: no new interface. Confirms the drop contract.

- [ ] **Step 1: Write the failing tests and remove superseded ones**

In `backend/tests/test_google_careers_spider.py`, delete `test_job_page_tokyo_sw_yields_full_dict`, `test_job_page_no_tokyo_term_yields_nothing`, `test_find_location_returns_first_tokyo_term`, and `test_job_page_no_leading_id_yields_empty_id` (they assert the removed term-scan). Replace with:

```python
def test_job_page_non_japan_tuple_yields_nothing() -> None:
    url = "https://careers.google.com/jobs/results/7-swe/"
    body = (
        '<html><head><title>T</title></head><body><script>'
        '[["Bangalore, India",["Bangalore, India"],null,null,"Bangalore","IN"]]'
        "</script></body></html>"
    )
    spider = GoogleCareersSpider()
    assert list(spider.parse_job(_job_response(body, url))) == []


def test_job_page_without_tuple_yields_nothing() -> None:
    url = "https://careers.google.com/jobs/results/8-swe/"
    body = "<html><body><p>Tokyo, Japan</p></body></html>"
    spider = GoogleCareersSpider()
    assert list(spider.parse_job(_job_response(body, url))) == []
```

- [ ] **Step 2: Run tests to verify non-JP fails against Task 1 code**

Run: `uv run --package jobsearch-backend pytest "backend/tests/test_google_careers_spider.py::test_job_page_non_japan_tuple_yields_nothing" -v`

Expected: FAIL — Task 1's `parse_job` yields the item regardless of country (no `JP` guard yet). The no-tuple test already passes (Task 1 returns `None` → drop).

- [ ] **Step 3: Add the `country == "JP"` guard in `parse_job`**

In `parse_job`, after `_find_location_tuple` returns `(city, country)`, add: if `country != "JP"`, `return`. Then yield the item.

- [ ] **Step 4: Run the full spider test file**

Run: `uv run --package jobsearch-backend pytest backend/tests/test_google_careers_spider.py -v`

Expected: PASS — all remaining tests, including the guard/redirect tests (`test_job_redirect_target_*`, `test_permitted_scope_*`), which do not touch `parse_job`.

- [ ] **Step 5: Commit**

```bash
git add backend/app/ingestion/spiders/google_careers.py backend/tests/test_google_careers_spider.py
git commit -m "feat(pbi6): drop non-Japan and tuple-less job pages at the spider"
```

---

## Task 3: Carry `country`/`city` through the draft boundary and normalize

**Files:**
- Modify: `backend/app/ingestion/drafts.py`
- Modify: `backend/app/ingestion/normalize.py`
- Modify: `backend/app/ingestion/sources/google_careers.py`
- Test: `backend/tests/test_normalize.py`, `backend/tests/test_google_careers_source.py`

**Interfaces:**
- Consumes: spider dict keys `"city"`, `"country"` (Task 1/2).
- Produces: `JobDraft` gains `city: str | None = None` and `country: str | None = None` (trailing, defaulted, so the positional construction in `test_ingest_cli.py` keeps working). `normalize_country(raw: str | None) -> str | None` and reuse of `normalize_location` for city. `GoogleCareersSource.fetch()` populates both.

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_normalize.py`:

```python
from app.ingestion.normalize import normalize_country


def test_normalize_country_uppercases_two_letter_code() -> None:
    assert normalize_country("jp") == "JP"
    assert normalize_country(" JP ") == "JP"


def test_normalize_country_rejects_non_two_letter() -> None:
    assert normalize_country("") is None
    assert normalize_country("JPN") is None
    assert normalize_country(None) is None
```

Append to `backend/tests/test_google_careers_source.py` a draft-level test. It uses the same `FakeSource(GoogleCareersSource)` + `_run_crawl` override seam the file already uses for canned dicts:

```python
def test_fetch_populates_normalized_city_and_country() -> None:
    canned: list[dict[str, str | None]] = [
        {
            "title": "SWE",
            "location": "Tokyo, Japan",
            "city": "  tokyo ",
            "country": "JP",
            "external_job_id": "123",
            "url": "https://careers.google.com/jobs/results/123-software-engineer/",
        },
    ]

    class FakeSource(GoogleCareersSource):
        def _run_crawl(self, spider: object) -> list[dict[str, str | None]]:
            return canned

    drafts = list(FakeSource().fetch())
    assert drafts[0].city == "tokyo"
    assert drafts[0].country == "JP"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run --package jobsearch-backend pytest backend/tests/test_normalize.py -k normalize_country -v`

Expected: FAIL — `ImportError: cannot import name 'normalize_country'`.

- [ ] **Step 3: Implement the changes**

In `normalize.py`, add:

```python
import re

_COUNTRY_CODE = re.compile(r"^[A-Z]{2}$")


def normalize_country(country: str | None) -> str | None:
    """Uppercase a 2-letter ISO country code; anything else becomes ``None``."""
    if country is None:
        return None
    code = country.strip().upper()
    return code if _COUNTRY_CODE.match(code) else None
```

In `drafts.py`, add the two trailing fields with defaults to `JobDraft`:

```python
    city: str | None = None
    country: str | None = None
```

In `sources/google_careers.py` `fetch()`, pass the new fields when constructing `JobDraft`, normalizing with `city=normalize_location(raw.get("city"))` and `country=normalize_country(raw.get("country"))`.

`city` is **case-preserving** (decided): `normalize_location` applies NFKC + whitespace collapse only, no casefold — city is a display/filter string emitted by the page's own tuple, and Japan city names are already consistently title-cased on-page. Do **not** titlecase/lower it.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run --package jobsearch-backend pytest backend/tests/test_normalize.py backend/tests/test_google_careers_source.py -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/ingestion/drafts.py backend/app/ingestion/normalize.py backend/app/ingestion/sources/google_careers.py backend/tests/test_normalize.py backend/tests/test_google_careers_source.py
git commit -m "feat(pbi6): carry normalized city+country on JobDraft"
```

---

## Task 4: Persist `country`/`city` — model, migration, and upsert backfill

**Files:**
- Modify: `backend/app/models/job.py`
- Create: `backend/alembic/versions/0005_job_location.py`
- Modify: `backend/app/ingestion/service.py`
- Test: `backend/tests/test_job_model.py`, `backend/tests/test_ingestion_service.py`, `backend/tests/test_migration_0005.py` (create)

**Interfaces:**
- Consumes: `JobDraft.city`/`JobDraft.country` (Task 3).
- Produces: `Job.country: Mapped[str | None]`, `Job.city: Mapped[str | None]`, composite index `ix_jobs_country_city`. `IngestionService` writes them on create and backfills on both re-sight paths via a private `_apply_sighting(job, draft, now)`.

- [ ] **Step 1: Write the failing tests**

In `backend/tests/test_job_model.py`, update `test_jobs_table_has_expected_columns` to include `"country"` and `"city"` in the expected set, add a nullable assertion for each, and add to `test_jobs_indexes_created` `assert "ix_jobs_country_city" in index_names`.

In `backend/tests/test_ingestion_service.py`, add:

```python
def test_new_draft_stores_country_and_city(session_factory) -> None:
    draft = _draft("123")
    draft = JobDraft(
        external_job_id="123", title="SWE", company=None, location="Tokyo, Japan",
        url="https://x/123-swe/", city="Tokyo", country="JP",
    )
    service = IngestionService(FakeSource([draft]), session_factory, now_provider=lambda: FIXED_NOW)
    service.run()
    with session_factory() as s:
        job = s.scalar(select(Job))
        assert job.city == "Tokyo"
        assert job.country == "JP"


def test_recrawl_backfills_country_and_city_on_existing_row(session_factory) -> None:
    # Pre-existing row with null city/country (simulates pre-migration data).
    with session_factory() as s:
        s.add(Job(source="test_source", external_job_id="123", title="SWE",
                  company=None, location="Tokyo", city=None, country=None))
        s.commit()
    draft = JobDraft(external_job_id="123", title="SWE", company=None,
                     location="Tokyo, Japan", url="https://x/123-swe/",
                     city="Tokyo", country="JP")
    service = IngestionService(FakeSource([draft]), session_factory, now_provider=lambda: FIXED_NOW)
    result = service.run()
    assert result.seen == 1
    with session_factory() as s:
        job = s.scalar(select(Job))
        assert job.city == "Tokyo"
        assert job.country == "JP"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run --package jobsearch-backend pytest backend/tests/test_job_model.py::test_jobs_table_has_expected_columns backend/tests/test_ingestion_service.py -k "country" -v`

Expected: FAIL — columns missing; `job.city` `AttributeError`/null.

- [ ] **Step 3: Add model columns and index**

In `backend/app/models/job.py`, add to `Job`:

```python
    city: Mapped[str | None] = mapped_column(Text, nullable=True)
    country: Mapped[str | None] = mapped_column(Text, nullable=True)
```

and to `__table_args__`:

```python
        Index("ix_jobs_country_city", "country", "city"),
```

- [ ] **Step 4: Upgrade the service to write and backfill**

In `backend/app/ingestion/service.py`, extract a small helper and call it from both the re-sight branch and the `IntegrityError` re-read branch:

```python
@staticmethod
def _apply_sighting(job: Job, draft: JobDraft, now: datetime) -> None:
    job.last_seen_at = now
    job.city = draft.city
    job.country = draft.country
```

Use `existing.last_seen_at = now` → `self._apply_sighting(existing, draft, now)` in both places; on create, set `city=draft.city, country=draft.country` on the `Job(...)`.

- [ ] **Step 5: Run unit tests to verify they pass**

Run: `uv run --package jobsearch-backend pytest backend/tests/test_job_model.py backend/tests/test_ingestion_service.py -v`

Expected: PASS.

- [ ] **Step 6: Write the migration and its (Postgres-gated) test**

Create `backend/alembic/versions/0005_job_location.py` following the `0004` style: `revision = "0005"`, `down_revision = "0004"`; `upgrade()` does `op.add_column("jobs", sa.Column("city", sa.Text(), nullable=True))`, `op.add_column("jobs", sa.Column("country", sa.Text(), nullable=True))`, and `op.create_index("ix_jobs_country_city", "jobs", ["country", "city"])`; `downgrade()` drops the index then both columns. Create `backend/tests/test_migration_0005.py` mirroring `test_migration_0003.py` (module-level `pytestmark = pytest.mark.ingest`, `DATABASE_URL` fixture) asserting `jobs` has nullable `city`/`country` columns and an `ix_jobs_country_city` index after upgrade.

- [ ] **Step 7: Commit**

```bash
git add backend/app/models/job.py backend/alembic/versions/0005_job_location.py backend/app/ingestion/service.py backend/tests/test_job_model.py backend/tests/test_ingestion_service.py backend/tests/test_migration_0005.py
git commit -m "feat(pbi6): persist country+city on jobs with re-crawl backfill"
```

---

## Task 5: Expose `country`/`city` on the shared contract and frontend

**Files:**
- Modify: `shared/jobsearch_shared/schemas.py`
- Modify: `backend/tests/test_job_response.py`, `shared/tests/test_job_response.py`
- Modify: `frontend/src/api.ts`, `frontend/src/pages/JobDetailPage.tsx`

**Interfaces:**
- Consumes: `Job.city`/`Job.country` (Task 4).
- Produces: `JobResponse.city: str | None`, `JobResponse.country: str | None`; frontend `Job` interface gains both; detail page shows `city, country` under the existing location row.

- [ ] **Step 1: Write the failing tests**

In `shared/tests/test_job_response.py::test_job_response_field_set_is_exact`, add `"city"` and `"country"` to the expected set. In `backend/tests/test_job_response.py::test_job_response_validates_orm_instance`, after validation, add `assert resp.city is None` and `assert resp.country is None` (the `Job` fixture omits them).

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest shared/tests/test_job_response.py backend/tests/test_job_response.py -v`

Expected: FAIL — `JobResponse` lacks `city`/`country`.

- [ ] **Step 3: Add fields to `JobResponse`**

In `shared/jobsearch_shared/schemas.py`, add `city: str | None` and `country: str | None` to `JobResponse` (after `location`). The backend route and `JobResponse.model_validate(job)` pick them up automatically — no route change.

- [ ] **Step 4: Frontend types + display**

In `frontend/src/api.ts`, add `city: string | null;` and `country: string | null;` to the `Job` interface. In `frontend/src/pages/JobDetailPage.tsx`, below the existing location row, render `city`/`country` when present (e.g. a "Region" row showing `{job.city}, {job.country}`). Keep the existing `location` row unchanged.

- [ ] **Step 5: Run tests and typecheck**

Run: `uv run pytest shared/tests/test_job_response.py backend/tests/test_job_response.py -v` → PASS.
Run: `cd frontend && npm run typecheck` → PASS.

- [ ] **Step 6: Commit**

```bash
git add shared/jobsearch_shared/schemas.py shared/tests/test_job_response.py backend/tests/test_job_response.py frontend/src/api.ts frontend/src/pages/JobDetailPage.tsx
git commit -m "feat(pbi6): expose city+country on JobResponse and detail page"
```

---

## Verification (gates)

Run in order; all must pass:

```bash
make lint
make typecheck
make test
```

Then the live acceptance gate (opt-in, Postgres + network):

```bash
make migrate            # applies 0005
make test-integration   # test_real_crawl_yields_nonempty must now be green
```

Bounded manual smoke (optional but recommended): run `make ingest TRIGGER=manual`
against the local DB, then `curl 'localhost:8000/jobs?source=google_careers'`
and confirm rows appear with non-null `city`/`country`. Expect `crawl_runs` to
show a `succeeded` row with `created > 0`.

**Gate 3 is done when** `test_real_crawl_yields_nonempty` passes and the unit
suite pins the yield / no-tuple-drop / non-JP-drop cases.

## Follow-on (not this plan)

- Freshness ("spot new listings in place X") — a later layer over `first_seen_at`,
  adding country/city query filters and a route.
- Region-level grouping (Tokyo-metro across cities) — needs a
  city→region mapping we maintain; the page exposes city+country only.
