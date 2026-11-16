# Location Extraction (Revision 2) — Design

**Status:** supersedes the extraction technique in
`2026-11-16-pbi6-location-extraction-design.md`. The schema, migration, API
contract, and re-crawl backfill from that spec stand unchanged; only *how the
spider reads location* changes.

## Why a revision

The first design extracted location from a fixed-position regex:

```
[["<city>, <country>",["<city>, <country>"],null,null,"<city>","<CC>"]]
```

A live audit against five hand-verified jobs proved it wrong for every
non-Japan job and silently labelled them all `Tokyo / JP`:

| job id            | true primary location | first design stored |
|-------------------|-----------------------|---------------------|
| 129819530682606278| Sydney NSW, Australia | Tokyo / JP          |
| 78601150982431430 | Zürich, Switzerland   | (dropped / wrong)   |
| 102729755412832966| New York, NY, USA     | Tokyo / JP          |
| 139033052381618886| Mountain View, CA, USA| Tokyo / JP          |
| 80779223387513542 | Tokyo, Japan          | Tokyo / JP          |

Two independent faults:

1. **Position dependence.** The tuple shape is not fixed. Japan jobs use
   `[display,[display],null,null,city,"JP"]`; jobs with a state use
   `[display,[display],city,null,STATE,"CC"]` (slot 5 is the *state* `NSW`,
   not the country). A regex anchored on `null,null` only ever matches the
   Japan shape — it can never return Sydney or NYC.
2. **Decoy tuples.** Every page embeds dozens of location tuples: Google's
   fixed office list (Sunnyvale / Mountain View / San Bruno / …), related
   jobs, and the job's own record. "First matching tuple" grabs a decoy.

## What the page actually provides (verified against the 5 fixtures)

- **Primary location, as display text.** The job header block renders the
  primary location first:

  ```html
  <span class="pwO9Dc vo5qdf">
    <i ...>place</i>
    <span class="r0wTof ">Zürich, Switzerland</span>   <!-- primary -->
    <span class="r0wTof p3oCrc">; London, UK</span>     <!-- alternatives -->
  </span>
  ```

  The first `<span class="r0wTof ">` (with the trailing space in the class, no
  `p3oCrc`) is the primary display string. Matched 5/5.

- **Primary country code.** The job's own record — the `AF_initDataCallback`
  `ds:0` blob keyed by the job's own id — carries the location code in a
  sign-in URL parameter: `loc=AU`, `loc=CH`, `loc=US`,
  `loc=JP`. Matched 5/5, including Zürich (whose country has *no* office
  tuple in the blob — `loc=` is the only place it appears).

- **City.** Derived from the primary display string: the text before the first
  comma (`"Sydney NSW, Australia"` → `Sydney`, `"Tokyo, Japan"` → `Tokyo`,
  `"New York, NY, USA"` → `New York`). Case-preserving.

## Decision: one row per job, primary location

A job may list several offices ("share your preferred working location from
the following: Zürich, Switzerland; London, UK"). The job still has **one
primary location** — the `loc=` code and the first header span agree on it in
all five fixtures. This revision stores that single primary location in the
existing `jobs.city` / `jobs.country` columns and the display string in
`jobs.location`. Multi-location modelling (a `job_locations` table) is out of
scope; see "Deferred".

## Extraction algorithm (replaces `_find_location_tuple`)

Given `response.text`:

1. `primary_display` = first match of
   `<span class="pwO9Dc vo5qdf">` … `place</i><span class="r0wTof ">([^<]*)</span>`.
   If absent → drop the page (drift; never guess).
2. `country` = first `loc=([A-Z]{2})` inside the job's own record
   (`data:[["<external_job_id>"`). If absent → fall back to:
   a `([A-Z]{2})` code parsed from the *last* comma-separated token of
   `primary_display` ("Sydney NSW, Australia" → `AU`? no — that token is a
   country *name*), so instead: if step 2 fails, drop the page. Never guess a
   country.
3. `city` = `primary_display` up to the first comma, trimmed. Empty → `None`.
4. Japan scope: yield only when `country == "JP"` (unchanged). The caller still
   filters; non-JP pages are dropped at the spider.

The spider keys the record lookup by `external_job_id`, which it already knows
from the sitemap URL — so the record anchor is the job's own id, not a
positional guess.

## Ground-truth fixtures (regression tests)

Encode all five as fixtures. Each asserts the extracted
`(display, city, country)`:

| id                | display                  | city         | country |
|-------------------|--------------------------|--------------|---------|
| 129819530682606278| Sydney NSW, Australia    | Sydney       | AU      |
| 78601150982431430 | Zürich, Switzerland      | Zürich       | CH      |
| 102729755412832966| New York, NY, USA        | New York     | US      |
| 139033052381618886| Mountain View, CA, USA   | Mountain View| US      |
| 80779223387513542 | Tokyo, Japan             | Tokyo        | JP      |

Only the Tokyo one is yielded by `parse_job` (JP scope). The other four assert
the *extractor* is correct and that `parse_job` drops them. A separate test
asserts that a page whose only Tokyo-like tuple is a decoy (a non-JP page with
a stray Tokyo office tuple) is **not** reported as Tokyo — the exact bug that
shipped.

## Unchanged from revision 1

- `jobs.city` / `jobs.country` nullable columns, `ix_jobs_country_city` index,
  migration 0005.
- `JobResponse.city` / `country` (default `None`), API + frontend rendering.
- `_apply_sighting` re-crawl backfill (overwrite per spec §7.5).
- `normalize_country` uppercasing.
- Drift signal via `crawl_runs`.

## Deferred

- **Multi-location jobs** (preferred-location alternatives): a job open in
  Zürich *or* London is stored with its primary (Zürich) only. A `job_locations`
  table and an alternative-locations API are future work.
- **Data already written by revision 1** is wrong for non-JP jobs and has been
  overwritten with `Tokyo/JP`. Re-crawl with revision 2 corrects JP jobs; rows
  mis-stored as `Tokyo/JP` that are actually non-JP will be overwritten to null
  (they are dropped at the spider, so never re-sighted) or corrected on their
  next re-sight. A one-shot repair pass over the existing table is recommended
  before trusting `country`/`city` as a filter (tracked separately).
