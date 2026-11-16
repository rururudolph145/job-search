# PBI 1 — Jobs Schema: Design Spec

> Status: draft for review
> Date: 2026-10-13
> Depends on: — (first data-layer PBI)
> Blocks: PBI 2 (source ingestion), PBI 3 (normalization + dedup keys), PBI 4 (query routes)

## 1. Purpose

Establish the first persistent domain schema for the Job Search Intelligence
Platform: the `jobs` table, its SQLAlchemy ORM model, an Alembic migration, and a
thin repository layer. This is the storage target that PBI 2 ingests into and
that PBI 3 derives canonical identity keys from.

## 2. Scope decision — deliberate deviation from the tracker

The PBI tracker states PBI 1 is: "`jobs`, `companies`, `job_sources` tables +
Alembic migration + repositories." **This spec ships only one table (`jobs`).**

The user's explicit directive during design was *"remove what's not necessary for
MVP."* Applying that to the tracker's wording:

- **`companies` is cut.** At MVP, a company is a display string on a job, not a
  normalized entity. The `companies` table's job — collapsing "Google" /
  "Google LLC" / "Google Japan" into one identity — is exactly PBI 3's
  "canonical job identity across … ATS providers" concern. Introducing the table
  now means an empty table with no writer.
- **`job_sources` is cut.** In MVP nothing consumes feed configuration: the
  Scrapy spike hardcodes its sitemap URL. A `job_sources` table would be config
  with no reader. Replaced by a plain `source` text slug on `jobs` (§3), which
  is enough to distinguish a second source later.
- **`external_job_id` is kept** on `jobs` even though source-lookup belongs to
  PBI 3 — it is the one identity field PBI 3's key derivation will need, and the
  Scrapy spike already surfaces it (the `{id}` in the result URL).

**Consequence to manage:** `frontend/src/pages/pbis.ts` mirrors the tracker text
and is pinned by `PbiTrackerPage.test.tsx`. The tracker line for PBI 1 says three
tables. This spec will update the tracker text (and the frontend mirror in a
later PBI-1 step) so the displayed roadmap does not silently contradict the
schema. See §8.

## 3. Data model

One table, `jobs`. Column set is deliberately minimal — every column was checked
against "is there a writer in PBI 1 or PBI 2?"

| Column | Type | Null | Default | Notes |
|---|---|---|---|---|
| `id` | `BIGINT` | no | autoincrement PK | Bigint autoincrement per design decision. |
| `source` | `TEXT` | no | — | Short slug, e.g. `google_careers`. Not an enum; not a FK. |
| `external_job_id` | `TEXT` | yes | — | Provider's own id (the `{id}` in a Google Careers result URL). Nullable — not every future source exposes one. |
| `title` | `TEXT` | no | — | Job title. |
| `company` | `TEXT` | yes | — | Denormalized display string for MVP. Nullable — a scraped page may not name the employer. Becomes an FK to `companies` in PBI 3. |
| `location` | `TEXT` | yes | — | Raw location text as scraped (e.g. `"Tokyo"`). Normalization is PBI 3. |
| `first_seen_at` | `TIMESTAMPTZ` | no | `now()` | When we first observed the posting. PBI 8. |
| `last_seen_at` | `TIMESTAMPTZ` | no | `now()` | Updated on every re-crawl that observes the posting. PBI 8. |
| `updated_at` | `TIMESTAMPTZ` | no | `now()` | Row audit; changes on any mutation. |

**Considered and deliberately excluded** (each has no producer in PBI 1–2, and
adding a column later is a one-line migration):

- `description`, `requirements` (JSONB), `employment_type` — the Scrapy spike
  yields none of these; nothing writes them.
- `content_hash` — this is a dedup-key concept and belongs to **PBI 3**.
- `status` — the user confirmed this means *internal lifecycle state*
  (active / disappeared_suspected / confirmed_gone), which is owned by **PBI 8**.
  A column that only ever holds its default is dead weight.
- structured location columns, `posted_at` — deferred; raw text + PBI 3
  normalization covers the MVP.

### Indexes and constraints

- PK on `id` (implicit).
- **Non-unique index on `(source, external_job_id)`** — not unique yet, because
  uniqueness is a dedup concern (PBI 3). The index exists so PBI 3's key lookup
  is cheap and so PBI 2 upserts can query efficiently.
- Index on `last_seen_at` — PBI 8's disappeared-job scan reads by staleness.

No unique constraint is added in PBI 1. Encoding a uniqueness rule now would
pre-empt PBI 3's identity decision, which is the explicitly-owned boundary.

## 4. ORM layer

Follow the existing repo conventions exactly:

- A single `Job` model in `backend/app/models/job.py`, subclassing
  `app.models.base.Base` (already exists as a bare `DeclarativeBase`).
- **SQLAlchemy 2.0 typed style**: `Mapped[...]` annotations with `mapped_column(...)`.
  This type-checks under the repo's strict mypy (`disallow_untyped_defs`,
  `no_implicit_optional`).
- Types: `Mapped[int]` for `id`; `Mapped[str]` / `Mapped[str | None]` for text;
  `Mapped[datetime]` used with `DateTime(timezone=True)` for the timestamptz trio.
  Use SQLAlchemy's native `Uuid`/`DateTime` types only as needed; here all are
  int/text/datetime.
- Timestamps: `server_default=func.now()` for the DB-side defaults, and
  `onupdate=func.now()` on `updated_at` so mutations bump it without app code.
- **Export `Job` from `backend/app/models/__init__.py`** — Alembic's `env.py`
  uses `target_metadata = Base.metadata` and only the models imported into that
  package are visible to autogenerate. This is a required step, not optional.

## 5. Migration

- New Alembic revision chaining from the existing baseline:
  `down_revision = "0001"` (baseline at
  `backend/alembic/versions/0001_empty.py`).
- Follow the established convention: zero-padded sequential string revision id
  (`"0002"`), plain `upgrade()` / `downgrade()`.
- `upgrade()` creates `jobs`, its indexes, and the timestamptz defaults;
  `downgrade()` drops the table (and indexes via the table drop).
- The migration may be autogenerated then hand-checked, or written by hand — but
  the committed result must match `Base.metadata` exactly so a future
  autogenerate produces no drift.
- Verified with `make migrate` against the Docker Postgres
  (`docker compose up -d` first).

## 6. Repository layer

Add `backend/app/repositories/job.py` (the package exists but is empty) with a
thin `JobRepository`. **No business logic** — dedup, normalization, and upsert
policy are PBI 2/3. MVP primitives:

- `get(session, job_id) -> Job | None`
- `list(session, *, limit, offset) -> list[Job]`
- `add(session, job: Job) -> Job` (add + flush; commit left to the caller/session
  context, matching the existing `get_session` context-manager contract which
  does not commit for you)
- `find_by_external_id(session, *, source, external_job_id) -> Job | None`

Follow the existing session contract: repositories take a `Session`; callers use
`with get_session() as session:`.

## 7. Shared contracts

Add a `Job`-shaped Pydantic response model to
`shared/jobsearch_shared/schemas.py` (the current sole contract is
`HealthResponse`) with `ConfigDict(from_attributes=True)`, and thin-re-export it
through `backend/app/schemas/__init__.py` per the established pattern. PBI 4
will consume it; defining it now keeps the ORM↔contract boundary explicit. Keep
it to the columns in §3 — do not expose internal-only fields.

## 8. Tracker + frontend sync

Update the PBI 1 line in `implementation_checklist/pbi_tracker.md` to reflect
the single-table MVP ("`jobs` table + Alembic migration + repository"), and
mirror the change in `frontend/src/pages/pbis.ts` so
`PbiTrackerPage.test.tsx` stays green. Note the deferred `companies` /
`job_sources` tables as a PBI 3 concern in the tracker text.

## 9. Testing

Match the existing test conventions (standalone modules, no `conftest.py`, SQLite
`:memory:`):

- **Model/metadata test**: `Base.metadata.create_all(engine)` on
  `sqlite:///:memory:` succeeds; assert the `jobs` table and expected columns
  exist. (Note: `TIMESTAMPTZ` `server_default=now()` behaves differently on
  SQLite — the test asserts schema shape, not default evaluation.)
- **Repository tests**: build an in-memory engine, create tables, monkeypatch
  `app.db.engine.engine` (the established injection pattern in
  `backend/tests/test_engine.py`), then exercise `add` / `get` /
  `find_by_external_id` / `list`.
- **Shared contract test**: roundtrip a `Job` response model via
  `model_validate(..., from_attributes=True)` against a `Job` ORM instance.
- **Migration test** (Postgres-only, may be marked to skip without Docker): run
  `upgrade head` then `downgrade base` cleanly.

All new functions fully annotated (`-> None`, typed params) for strict mypy.

## 10. Verification (end-to-end)

1. `make lint` — ruff check + format.
2. `make typecheck` — mypy strict over `backend/app` and `shared/jobsearch_shared`.
3. `make test` — pytest across `backend/tests` + `shared/tests`.
4. `make db-up && make migrate` — migration applies against real Postgres; then
   `psql` (or `docker compose exec`) to confirm the `jobs` table and indexes.
5. Confirm `alembic upgrade head` is idempotent and `downgrade base` is clean.

## 11. Out of scope

Ingestion (PBI 2), dedup/normalization logic and `content_hash` (PBI 3), query
routes (PBI 4), `companies`/`job_sources` tables (revisit at PBI 3), lifecycle
status and disappeared-job detection (PBI 8), search/embeddings (PBIs 10–13).
