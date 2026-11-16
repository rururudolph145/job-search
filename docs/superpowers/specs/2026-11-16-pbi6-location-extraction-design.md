# PBI 6 — Location Extraction (Gate 3): Design Spec

> Status: draft for review
> Date: 2026-11-16
> Depends on: PBI 2 (source ingestion), PBI 3 (normalization + identity)
> Supersedes the "client-rendered location" claim in
> [2026-10-27-pbi6-crawl-scheduler-design.md](2026-10-27-pbi6-crawl-scheduler-design.md)
> and the Follow-on sections of the two guard-ordering plans.

## 1. Purpose

The crawl currently records **0 jobs** end-to-end because `parse_job` scans the
page's `body//text()` for Tokyo-metro city names and drops any page it cannot
match. The two PBI 6 guard plans deferred this as "Gate 3 — location is
client-rendered". Live probing on 2026-11-16 shows that premise is **stale**:

- The location **is** in the server-rendered HTML, as a machine-readable tuple
  embedded in a JS data blob:
  `["Tokyo, Japan",["Tokyo, Japan"],null,null,"Tokyo","JP"]`
  = `[display, [display], ?, ?, city, ISO-3166 country code]`.
- A 40-page even sample of the 594 software-engineer sitemap `<loc>`s returned
  the tuple on **40/40** pages, exactly one tuple per page, country code `JP`,
  city `Tokyo` in all 40.

This spec replaces the fragile term-scan with structured extraction and makes
location a **filter dimension**, so the human partner can later narrow to
Japan → city for job hunting.

## 2. Intent and the why

The human partner is job hunting and wants to **spot fresh listings in a
specific place** — Japan now, down to Tokyo/Osaka/etc. later. Freshness itself
is **explicitly a later layer** (it will build on `first_seen_at` /
`last_seen_at`, which already exist). This spec's job is narrower and
foundational:

> Make the crawled **location data correct and structured**, so it can serve as
> a trustworthy `country → city` filter in a later freshness feature.

That "trustworthy" is the whole point. A freshness monitor is only useful if
"new Tokyo role" means *new and actually in Tokyo*. The current substring scan
would match "Tokyo" appearing in a job *description* of a non-Tokyo role — a
silent wrong-place error that erodes trust in the monitor. Structured extraction
removes that failure mode.

## 3. Goals

- Extract **country code** and **city** from the embedded location tuple on the
  Google Careers job page.
- Store them as structured, queryable fields on `jobs` (`country`, `city`),
  alongside the existing free-text `location` display string.
- Keep ingesting **all of Japan** (`country == "JP"`); drop pages that are not
  Japan or carry no location.
- Keep the existing API and dashboard working unchanged (the display
  `location` string is preserved).
- Re-crawl backfills `country`/`city` on existing rows via the normal upsert.

## 4. Non-goals

- **Freshness / "new listing" detection or surfacing.** Separate later layer.
- **Region/state-level granularity.** The page exposes city + country; anything
  coarser (Kanto, Tokyo-metro spanning multiple cities) is out of scope.
- **Other sources.** Only the Google Careers spider is touched. If JSON-LD
  (`JobPosting` `jobLocation`) is added with future sources, it is a separate
  spec.
- **A filter UI / query route for country or city.** This spec makes the *data*
  ready; filtering endpoints/UI are a later layer.
- **Cross-source location reconciliation.**

## 5. Anti-goals (what would make this a failure even if it "works")

- A location that is right on today's Tokyo-dominated sample but silently wrong
  (or silently dropped) the moment a non-Tokyo or multi-location role appears.
- A substring/term-scan path retained "just in case" that reintroduces
  false positives or makes the extraction rule ambiguous.
- Breaking the existing `location` display contract that the API/dashboard use.

## 6. Constraints

- The rule is structural: the filter is **`country == "JP"`**; city is extracted
  for display/future filtering, not for the current drop decision.
- **Structured-only, no DOM-text fallback** (decided). A page with no tuple or
  a non-`JP` code is dropped — same shape as today's "not found → drop", just
  on a reliable signal.
- **One tuple per page** is the observed reality; the design may *tolerate* more
  but must not depend on picking correctly among several. This spec assumes
  exactly one; multi-tuple handling is a builder's-call fallback (see §9).
- `country` and `city` are **nullable** on the model (old rows are null until
  re-crawl; existing unit tests and fixtures need not supply them).
- Google Careers' `careers.google.com/*` job URLs 301 to
  `www.google.com/about/careers/applications/*`; the extracted page is the
  redirected one. This already works (guard fix) and is not changed here.

## 7. Architecture — the change in one line

`parse_job` stops scanning body text for Tokyo terms and instead pulls
`(city, country)` out of the embedded location tuple; the draft boundary, the
`jobs` row, and the shared response gain `country` and `city`; ingestion filters
on `country == "JP"`.

### 7.1 Spider — `backend/app/ingestion/spiders/google_careers.py`

- Add a module-level compiled regex (or small helper) that extracts the location
  tuple from `response.text`. The verified shape in the HTML:
  ```
  [["Tokyo, Japan",["Tokyo, Japan"],null,null,"Tokyo","JP"]]
  ```
  Capture groups: display, city, country code.
- In `parse_job`:
  - Find the location tuple. If absent → `return` (drop).
  - If `country != "JP"` → `return` (drop). Japan scope is enforced **at the
    spider**: non-Japan jobs are never inserted (decided — expanding to other
    countries later means a re-crawl, which is accepted).
  - Otherwise yield the item including `city` and `country`.
  - **No new logging mechanism.** Production runs the source with
    `verbose=False`, so Scrapy's `LOG_ENABLED=False` swallows `self.logger.*`.
    The drift signal is the `crawl_runs` row: a run that produced zero drafts
    shows `created=0, seen=0` (and `skipped_no_id` as today). Decided: that is
    sufficient; do **not** add a separate non-Scrapy logger or a new
    `crawl_runs` column for this.
- Title extraction is unchanged (`og:title` / `<title>`).
- `external_job_id` extraction is unchanged.
- Remove the Tokyo-specific location logic (`TOKYO_TERMS`, `_find_location`) —
  it is superseded. (Builder detail: keep the file honest; stale constants that
  are no longer used should go.)

Builder's call (not decided here): whether to keep a narrow, documented
`data-testid`/DOM fallback. The decision in §6 is **structured-only**; the
builder should implement structured-only.

### 7.2 Draft boundary — `backend/app/ingestion/drafts.py`

`JobDraft` gains `country: str | None` and `city: str | None`. The display
`location` stays.

### 7.3 Source — `backend/app/ingestion/sources/google_careers.py`

`fetch()` copies `raw.get("city")`, `raw.get("country")` into the `JobDraft`,
normalizing like the other display fields (NFKC + whitespace collapse for city;
country uppercased, validated as two letters).

### 7.4 Model + migration — `backend/app/models/job.py`, `alembic/versions/0005_*.py`

- Add `country: Mapped[str | None]` (Text, nullable) and
  `city: Mapped[str | None]` (Text, nullable).
- Index: a composite `(country, city)` index supports the upcoming
  country → city filtering cheaply. (Builder's call on index name/convention;
  PBI 3's `ix_*` prefix is the local idiom.)
- Migration `0005` adds the two nullable columns + the index. No backfill SQL —
  re-crawl populates them (decided). Downgrade drops the index and columns.

### 7.5 Upsert — `backend/app/ingestion/service.py`

When creating a `Job`, write `country` and `city` from the draft. On
re-sighting an existing job, **also update `country`/`city`** (alongside the
`last_seen_at` bump) so re-crawl backfills old rows. Keep it minimal: no other
fields are refreshed today; adding country/city to the re-seeing path is the
only change and is intentional (it is how backfill happens).

### 7.6 Shared contract — `shared/jobsearch_shared/schemas.py`

`JobResponse` gains `country: str | None` and `city: str | None`. Additive, so
the existing response shape is preserved (clients ignore unknown fields).

### 7.7 API + frontend

- Route: no change — `JobResponse.model_validate(job)` picks up the new
  attributes automatically since the model carries them.
- Frontend (`frontend/src/api.ts` types, `JobDetailPage`, `JobsPage`):
  - Add `country`/`city` to the `Job` interface.
  - Display is optional for this spec; minimally, ensure typecheck stays green.
  - Optional (builder's call, low risk): show `city, country` on the detail
    page. Not required for the gate to pass — the requirement is that
    `location` still displays.

## 8. Data / verification

- **Unit tests (no network),** over captured HTML fixtures:
  - Tuple present + `JP` → item yielded with correct `city`/`country`/`location`.
  - Tuple present + non-`JP` → dropped.
  - Tuple absent → dropped.
  - Regex handles the exact on-wire shape incl. the escaped/null neighbours.
- **Source/service tests:** draft carries country/city; new job row stores them;
  re-sighting backfills them on an existing row that had nulls.
- **Migration test:** upgrade adds nullable columns + index; downgrade removes
  them (mirror the `test_migration_0003` pattern).
- **Live acceptance:** `make test-integration` `test_real_crawl_yields_nonempty`
  goes green (items are produced). Optionally a bounded manual crawl to eyeball
  `country`/`city` on a handful of real pages.
- **Gate 3 is done when** the live integration test yields non-empty drafts and
  the unit suite pins the three drop/yield cases.

## 9. What's left to the builder

- Exact regex/helper and its placement; how to fail safe if the tuple shape
  drifts (recommendation: match strictly, drop on no-match, so a format change
  surfaces as a zero-draft run — visible via `crawl_runs.created=0, seen=0` —
  rather than wrong data). No log line is added (decided; see §7.1).
- Multi-tuple pages: observed as one-per-page; if encountered, a documented rule
  (e.g. first `JP` tuple wins) is acceptable. Must not silently mis-pick.
- Index naming and whether the composite is `(country, city)` or two single
  indexes — favor what the eventual `WHERE country = ? AND city = ?` query needs.
- Whether to add a `city, country` display line on the detail page (optional).
- Whether to keep the `TOKYO_TERMS` constant for any other purpose (expected:
  remove).

## 10. Open questions for the human partner

None blocking. One thing worth flagging for later, not decided here:

- The page exposes **city + country**, not region/state. When "finer than
  Tokyo/Osaka" is wanted (e.g. Tokyo-metro as a group), we will need a
  city→region mapping we maintain ourselves. Out of scope now; noted so it is
  not a surprise later.

## Appendix A — Evidence (2026-11-16 live probes)

- Sitemap: `https://careers.google.com/jobs/sitemap` → 301 →
  `https://www.google.com/about/careers/applications/jobs/sitemap.xml`, 200.
  `3267` `<loc>`, `594` matching `software-engineer`.
- Single job page: 200, `text/html`, ~1.29 MB. Tuple present twice-ish in blob +
  rendered DOM `<span>Tokyo, Japan</span>`. `og:title` clean.
- Production `parse_job` run against one live page: `item_scraped_count = 1`.
- 40-page even sample: tuple on 40/40; `country` distribution `{JP: 40}`;
  distinct cities `1` (`Tokyo`); zero multi-tuple pages; zero no-tuple pages.
