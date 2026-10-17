# PBI 3 — Normalization + Dedup Keys: Design Spec

> Status: draft for review
> Date: 2026-10-17
> Depends on: PBI 1 (jobs schema + `JobRepository`), PBI 2 (source ingestion)
> Blocks: PBI 4 (query routes), PBI 7 (failure recovery), PBI 8 (disappeared-job detection)

## 1. Purpose

Give the `jobs` table a real uniqueness guarantee. PBI 1 deliberately shipped no
unique constraint — its spec states plainly that *"Encoding a uniqueness rule now
would pre-empt PBI 3's identity decision."* PBI 2 dedups only as a convenience
(*"not as a dedup policy"*). PBI 3 is where that decision is finally made.

**Scope, in one line:** make `(source, external_job_id)` the unique identity of a
job, canonicalize the fields that feed it, and harden the ingest path against the
constraint the schema now enforces.

This is a **data-layer PBI**. It ships no endpoint and no contract change (§6).

## 2. What the evidence changed

The design was originally framed around a `content_hash` over
`(title, company, location)`, following the `content_hash` field PBI 1 deferred
to PBI 3. **Inspecting the live database reversed that plan**, and the reversal is
the most important thing in this spec.

The `jobs` table holds **711 rows**, all `source = 'google_careers'`. Two findings:

1. **`company` is `NULL` on every row.** PBI 2's spec anticipated this (*"company:
   best-effort extraction; **often `None`**"*), but at 711/711 it is not
   occasional — it is total. Any hash including `company` would hash `NULL` for
   the entire corpus.
2. **26 groups of `(title, company, location)` already collide**, and every group
   is *distinct requisitions sharing a title*. The largest:

   | title | n | distinct `external_job_id`s |
   |---|---|---|
   | `Senior Software Engineer` | 5 | 5 |
   | `Software Engineer III, Full Stack` | 5 | 5 |
   | `Senior Software Engineer, Site Reliability Engineering` | 5 | 5 |
   | `Staff Software Engineer, Infrastructure` | 3 | 3 |

So a `content_hash` over `(title, company, location)` — which, given finding 1,
is really a hash of `title + location` — would **not deduplicate. It would delete.**
Five real, open, separately-requisitioned jobs collapse to one.

Meanwhile `external_job_id` already distinguishes those rows exactly. The
provider's own id *is* the identity, and the schema was already carrying it. PBI 3
does not need to invent an identity; it needs to **enforce the one that exists.**

### 2.1 On `content_hash` specifically

A content hash in the ordinary sense — a fingerprint of a posting's *content*
(title, description, requirements) used to detect that a posting was **edited** —
is a different thing from a matching key, and it **cannot be built yet**.

`jobs` has no `description` or `requirements` column: PBI 1 cut them because the
Scrapy spike yields neither and nothing writes them. A content hash today would
hash `title + location + NULL`, i.e. exactly the thing that collides 26 times. It
would be a hash over fields carrying no content.

**Decision: no `content_hash` column in PBI 3.** It is deferred to whichever PBI
first scrapes job bodies — a PBI that also reopens PBI 2's compliance scope,
since detail pages are the `robots.txt` gray area PBI 2 documented. That is a
deliberate deferral with a named trigger, not an omission.

## 3. Scope decisions (locked during design)

| Decision | Choice |
|---|---|
| How far "canonical identity" reaches | **Dedup key only.** No `companies` table, no cross-ATS entity resolution. There is one source; cross-ATS matching has nothing to validate against. |
| Identity | **`(source, external_job_id)`**, made unique via a *partial* unique index. |
| `content_hash` | **Deferred** (§2.1). |
| Existing rows | **Constrain only.** No backfill, no re-normalization (§5.2 has the evidence). |
| Normalization scope | Conservative: slug-lowercase `source`, strip/validate `external_job_id`, NFKC + whitespace-collapse `title`/`company`/`location`. No casefolding of display fields, no company-suffix stripping, no location parsing. |
| Id-less jobs gap | **Documented**, not fixed (§4.3). |
| API surface | **None.** PBI 4 owns query routes. |

## 4. Components

### 4.1 The unique index — `backend/alembic/versions/0003_job_identity.py`

```
UNIQUE (source, external_job_id) WHERE external_job_id IS NOT NULL
```

Three deliberate properties:

- **Partial, not plain unique.** `external_job_id` is nullable by schema; PBI 1
  accepted that not every source exposes one. The `WHERE ... IS NOT NULL` clause
  makes the intent explicit rather than relying on Postgres's implicit
  multiple-`NULL`s-allowed behaviour: *this constraint governs rows that carry a
  provider id.* Rows without one are simply not covered — we do not assert an
  identity we do not have.
- **Scoped by `source`.** Provider ids are unique only *within* a provider; two
  ATSs can both emit `12345`. This is what makes the key meaningful once PBI 6
  adds a second source.
- **Named `uq_jobs_source_external_job_id`**, replacing the non-unique
  `ix_jobs_source_external_job_id` (identical column list; the unique index
  serves every lookup the old one did). The `ix_`→`uq_` rename makes the intent
  legible in `psql`.

Matching ORM change in `backend/app/models/job.py`: the `Index(...)` entry
becomes a unique index carrying the predicate.

**Correctness consequence, stated plainly:** dedup is **exact when the provider
supplies an id, and absent when it does not.** A posting with no
`external_job_id`, re-crawled under a new URL, will insert a second row. PBI 2
declines to construct a draft without an id, so this affects nothing today (§4.3).

### 4.2 `normalize.py` — `backend/app/ingestion/normalize.py`

A small module of **pure functions** — no I/O, no DB, no config. Pure
`str -> str` / `str | None -> str | None` signatures are trivially testable.

| Field | Transformation | Justification |
|---|---|---|
| `source` | lowercase, strip, collapse internal whitespace | It is a key component. `Google_Careers` and `google_careers` must not be two sources. |
| `external_job_id` | strip; empty ⇒ `None` | An id of `" "` is not an id. `None` puts the row outside the partial index, which is the correct semantic. |
| `title` | NFKC, collapse whitespace, strip | Scraped text carries `\xa0` and double spaces. NFKC folds lookalike unicode. |
| `company` | same as `title`; `None` → `None` | Currently always `NULL`; the function must handle it. |
| `location` | same as `title` | Handles Tokyo-metro variants. **No** structured parsing. |

**Deliberate non-transformations**, named so they do not creep in later:

- **No casefolding of `title`/`company`/`location`.** They no longer feed a unique
  key, so case is a display concern. Downcasing would alter what the user sees for
  no identity gain. (`source` is lowercased because it *is* a key component.)
- **No company suffix stripping** (`Inc`/`LLC`/`K.K.`). `company` is `NULL` on all
  711 rows; this cannot be tested.
- **No location canonicalization** (`"Tokio"` → `"Tokyo"`, country inference).
  Real entity work with no data to validate against.
- **No confusable folding beyond NFKC.** NFKC is a defined standard; further
  folding would be ad hoc.

**Call site:** the source→service boundary, where each `JobDraft` is constructed
(`GoogleCareersSource`). The invariant becomes *"every `Job` the service writes
already has canonicalized fields"* — one choke point.

**Honest gap:** normalizing at the write boundary does **not** re-normalize the
711 existing rows (§5.2).

### 4.3 `IngestionService` changes — `backend/app/ingestion/service.py`

PBI 2's `run()` does check-then-insert: read via `find_by_external_id`, then
either bump `last_seen_at` or insert, committing once at the end. With a unique
constraint in place the read stops being the guarantee and becomes an
optimization — the database now enforces identity.

**Change: keep the read, and handle `UniqueViolation` on insert deliberately.**
On violation, re-read and count the draft as `seen` rather than letting the
exception reach the CLI.

Rationale: it keeps `created` vs `seen` counting and the `last_seen_at` bump
driven by the existing read, makes the service correct under a **concurrent
writer** instead of merely usually-correct, and is honest about which layer
enforces identity.

**Behavioral change (a fix, not a regression):** if two drafts in one run carry
the same `(source, external_job_id)`, the first inserts and the second now counts
as `seen`. Before the constraint the second would have inserted a duplicate row.
No test covers this today; §7 adds one.

**Known gap — id-less jobs (documented, not fixed).**
`external_job_id` is **nullable**, and the partial index exists precisely to
acknowledge that case. But `IngestionService` looks up by
`(source, external_job_id)`, and PBI 2's source guarantees a non-empty id by
dropping any page where none parses (`skipped_no_id`). The consequence:

> A source producing legitimately id-less jobs yields **no drafts at all**, so
> its jobs are **never ingested** — silently invisible rather than stored with a
> `NULL` id. `jobs.external_job_id` is currently **unreachable-by-construction**:
> nullable in schema, never null in practice.

This is arguably correct for Google Careers (an id-less page is un-parseable),
but it is a hard-coded policy living in the source layer. It **cannot be fixed in
PBI 3** without knowing which source produces id-less jobs and how to dedup them
— exactly the cross-ATS work deferred by decision in §3. Recorded here and in a
code comment at the source's `skipped_no_id` path.

### 4.4 Repository and contract

**No changes.**

- `JobRepository.find_by_external_id` already exists and already does the lookup
  the constraint now backs; no new method is added (a method with no distinct
  caller would be dead weight).
- `JobResponse` already exposes the columns in `jobs`. With no new column (§2.1),
  the contract is unchanged. PBI 4 consumes it as-is.

## 5. Migration

### 5.1 Revision `0003`

Chains from `0002` (`backend/alembic/versions/0002_jobs.py`).

```
upgrade():
    drop index ix_jobs_source_external_job_id
    create UNIQUE index uq_jobs_source_external_job_id
        ON jobs (source, external_job_id) WHERE external_job_id IS NOT NULL

downgrade():
    drop index uq_jobs_source_external_job_id
    create index ix_jobs_source_external_job_id ON jobs (source, external_job_id)
```

- **Backfill: none needed — this is a finding, not a shortcut.** See §5.2.
- **Lock behaviour:** on Postgres `CREATE UNIQUE INDEX` takes a `SHARE` lock
  blocking writes. At 711 rows this is sub-second, so `CONCURRENTLY` is not worth
  it (it also cannot run inside Alembic's default transaction, needing
  `autocommit_block()`). Recorded so the choice is deliberate: at a large table
  size, `CONCURRENTLY` would be the answer.
- **`downgrade()` restores the original non-unique index**, so `upgrade head` →
  `downgrade base` remains clean.

### 5.2 Existing-rows inspection (evidence)

Run against the live Docker Postgres before writing this spec:

| Check | Result |
|---|---|
| Rows total | 711, all `google_careers` |
| Rows violating the new unique constraint | **0** |
| Rows with `NULL` `external_job_id` | **0** |
| `location` whitespace dirt | 0 |
| NBSP (`\xa0`) present | 0 |
| `source` case dirt | 0 |
| `external_job_id` whitespace / empty | 0 |
| `title` whitespace dirt | **1** (row `id=431`) |

**Conclusion: the migration is purely additive — it merges nothing and rewrites
nothing.** The constraint the design adds is already satisfied by the data, so
there is no backfill step to write. Had the original `content_hash` plan been
followed, this same table would have had 26 groups merged.

The single dirty row is left **unmodified**:

```
id=431  title='Software Engineer, AI/Machine Learning,  PhD, Early Career, 2027 Start'
                (double space after "Learning,")
```

It is display-only, no reader exists yet (PBI 4 owns routes), and rewriting
user-visible data is beyond the constraint the user approved. A re-normalization
pass over legacy rows is a separate small task if it is ever wanted. §7 pins this
with a regression test so a later contributor cannot add a re-normalization to
the migration without notice.

## 6. API surface

**PBI 3 ships none.** No new route, no contract change, no repository method
(§4.4). PBI 4 owns query routes and consumes `JobResponse` unchanged.

Called out explicitly because the tracker line — *"canonical job identity across
URLs and ATS providers"* — reads as if it might include a matching endpoint. It
does not: PBI 3 is a data-layer PBI, and the "across ATS providers" work is
deferred with its reason recorded in §3.

## 7. Testing

Conventions match the repo: standalone modules, no `conftest.py`, SQLite
`:memory:` for unit tests, `monkeypatch.setattr(engine_mod, "engine", ...)` where
the engine singleton is involved.

| File | Covers |
|---|---|
| `backend/tests/test_normalize.py` *(new)* | Pure functions: NFKC folding, `\xa0` → space, whitespace collapse, `None` passthrough for company/location, id strip and empty→`None`, source slug lowercasing. No DB. |
| `backend/tests/test_job_model.py` *(extend)* | Metadata asserts the unique index exists **with its `WHERE external_job_id IS NOT NULL` predicate**. |
| `backend/tests/test_job_repository.py` *(extend)* | Two rows with the same `(source, external_job_id)` → `IntegrityError`. Two rows with `NULL` ids → **both survive**. Same id, different `source` → both succeed. |
| `backend/tests/test_ingestion_service.py` *(extend)* | In-run duplicate id → second counts `seen`, one row. `UniqueViolation`-on-insert path re-reads and counts `seen`. Normalization applied to written values. |
| Migration test *(extend, Postgres-gated)* | `upgrade head` → constraint present and rejecting a duplicate; `downgrade` → non-unique index restored; `downgrade base` clean. |
| Dirty-row test *(new, small)* | Asserts row `id=431`'s double-space title is **unmodified** by the migration. |

Notes on two of these:

- **The `NULL`-id coexistence test is the important one.** The partial index is a
  deliberate choice, and a *plain* unique index would also pass a naive duplicate
  test — because Postgres allows multiple `NULL`s in a plain unique index too.
  Only a test inserting two `NULL`-id rows and asserting *both survive* proves the
  index is partial, and would catch the predicate being dropped in a refactor.
- **The dirty-row test is unusual** — pinning a known-bad value looks wrong. It
  exists so the "do not re-normalize legacy rows" decision (§5.2) is enforced by a
  failing test rather than by memory.

## 8. Verification (end-to-end)

1. `make lint` — ruff check + format.
2. `make typecheck` — mypy strict over `backend/app` and `shared/jobsearch_shared`.
3. `make test` — pytest across `backend/tests` + `shared/tests`.
4. `make db-up && make migrate` — `0003` applies against real Postgres.
5. In `psql`: confirm `uq_jobs_source_external_job_id` exists, is `UNIQUE`, and
   carries the `WHERE external_job_id IS NOT NULL` predicate; confirm
   `ix_jobs_source_external_job_id` is gone.
6. Attempt a manual duplicate insert in `psql` → rejected; attempt two `NULL`-id
   inserts → both accepted.
7. `make ingest` — a real run still succeeds and inserts no duplicates
   (PBI 2's verification §8 step 6 still holds).
8. `alembic downgrade base` → clean; `upgrade head` → idempotent.

## 9. Out of scope

- **`content_hash`** — deferred to whichever PBI first scrapes job bodies (§2.1).
- **`companies` table / company normalization** — deferred; `company` is `NULL` on
  all rows, so it cannot be validated.
- **Cross-ATS entity resolution** (same real-world job on two providers) — needs a
  second source and an accuracy evaluation.
- **`job_sources` table** — PBI 6.
- **Structured location columns, `description`/`requirements`** — later PBIs.
- **Query routes** — PBI 4.
- **Retry / backoff / idempotent writes** — PBI 7.
- **"Disappeared job" detection** — PBI 8, which this PBI unblocks by giving it a
  stable identity to attach to.
- **Re-normalizing the 711 legacy rows** — separate small task if ever wanted;
  §5.2 and §7 pin the current decision.

## 10. Adjacent loose end (carried forward from PBI 2)

The tracker still shows **PBI 1 as `[ ]`** although the schema, migration,
repository, and contract are implemented, tested, and committed — and PBI 2 has
since been built directly on top of it. PBI 2's spec §10 raised this and it is
still unresolved. PBI 3's own tracker line will be edited when this PBI lands, so
PBI 1's status is worth reconciling in the same pass. Not PBI 3's work, but the
same file.
