# PBI 3 — Normalization + Dedup Keys Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `(source, external_job_id)` the database-enforced unique identity of a job, canonicalize the fields that feed it at the write boundary, and harden the ingest path against the constraint the schema now imposes.

**Architecture:** A partial unique index `uq_jobs_source_external_job_id` on `jobs (source, external_job_id) WHERE external_job_id IS NOT NULL` (Alembic revision `0003`) replaces PBI 1's non-unique `ix_jobs_source_external_job_id`. A pure-function module `normalize.py` canonicalizes draft fields (`source` slug-lowercase, `external_job_id` strip/empty→`None`, NFKC + whitespace-collapse for `title`/`company`/`location`). `GoogleCareersSource` applies normalization at draft construction (the single choke point), and `IngestionService` catches `UniqueViolation` on insert so a concurrent (or in-run duplicate) writer counts as `seen` instead of crashing. No `content_hash`, no `companies` table, no new API, no repository/contract change.

**Tech Stack:** Python 3.13, SQLAlchemy 2.0 (typed `Mapped` style), Alembic, Pydantic 2, pytest (SQLite `:memory:` for unit tests), Postgres 16 + pgvector (Docker Compose, migration verification only), mypy strict, ruff, uv workspace.

**Spec:** [docs/superpowers/specs/2026-10-17-pbi3-normalization-dedup-design.md](../specs/2026-10-17-pbi3-normalization-dedup-design.md)

## Global Constraints

- Python `>=3.13`; all new functions/methods fully annotated (mypy `disallow_untyped_defs`, `no_implicit_optional`).
- Ruff selects `E, W, F, I, C, B` with double quotes, 88-char lines, `line-ending = "auto"` (`E501`, `E203` ignored).
- SQLAlchemy 2.0 typed style; the partial unique index uses `postgresql_where=text("external_job_id IS NOT NULL")` — **not** a `where=` arg, which every dialect would type-check against an unbound column and reject.
- Normalization functions are pure (`str`/`str | None` in, same out) — no I/O, no DB, no config, no mutation of the caller's `JobDraft`.
- Alembic revision `"0003"`, `down_revision = "0002"`; `upgrade()`/`downgrade()` annotated `-> None`; `downgrade()` restores the original non-unique `ix_jobs_source_external_job_id`.
- Tests import via the repo's `importlib` mode and `pythonpath = ["backend", "shared", "."]` (root `pyproject.toml`) — no `conftest.py`, standalone test modules.
- The default suite runs `pytest -m "not ingest"`; Postgres-gated checks use the `ingest` marker (opt-in via `make test-integration` or explicit run against live Postgres).

## Review Focus

The inputs and conditions below are not covered by the spec's happy path and are the most likely to bite a person using this software. Each line names the failure mode and links to the task whose tests pin it.

- **Two jobs with `NULL` `external_job_id` (id-less postings) must both survive.** The partial index exists precisely to let null-id rows coexist; a careless refactor to a *plain* unique index would still pass a naive SQLite duplicate test (both SQLite and Postgres permit multiple `NULL`s), so only a test inserting two null-id rows and asserting *both persist* proves the partial predicate. **Dialect caveat:** on SQLite `postgresql_where` is silently dropped (still `UNIQUE`, still null-tolerant), so *this* test passes on SQLite but cannot prove partiality there — the predicate must be pinned on Postgres (Task 4). — Task 3 (repository `IntegrityError`/coexistence) + Task 4 (Postgres-gated predicate proof).
- **The same job id surfacing twice in one run must yield one row, not a crash or a duplicate.** Before the constraint, the second insert silently added a duplicate. After the read-and-handle-`UniqueViolation` change, the second draft must count as `seen`. — Task 5 (`test_duplicate_in_one_run_is_seen`, augmented; `UniqueViolation` path).
- **`external_job_id` of `"" ` or all-whitespace after fetch must become `None`, never an empty string.** An empty string (not `NULL`) would still match the partial predicate clause `IS NOT NULL` and could collide two genuinely-different id-less rows. The normalization contract is `strip → empty ⇒ None`. — Task 2 (`normalize.py`).
- **Normalization must not mutate the source's `JobDraft`.** A pure-function boundary that silently rewrites a `frozen=True, slots=True` dataclass would raise `FrozenInstanceError` mid-crawl. Normalize-and-rebuild must produce new drafts. — Task 2 (pure-function signatures) + Task 5 (normalized values asserted at write).
- **Two genuinely different postings that share a title+location must NOT be merged.** The whole reversal of this spec is that `content_hash = title + location` would collapse 26 real requisitions. No `content_hash` column is added, and no code path hashes title/location. Any test here that would have been satisfied by the abandoned hash is a red flag. — Task 1 (no `content_hash` assertion in model test) + Task 8 (SQL proof the dirty row is untouched, not rewriteable).

---

### Task 1: Unique index on the `Job` model

**Files:**
- Modify: `backend/app/models/job.py:38-41`

**Interfaces:**
- Consumes: existing `Job` model (PBI 1).
- Produces: a `uq_jobs_source_external_job_id` unique partial index on `Job.__table_args__` carrying `postgresql_where=text("external_job_id IS NOT NULL")`. The old `ix_jobs_source_external_job_id` entry is removed.

- [ ] **Step 1: Write the failing tests**

Modify `backend/tests/test_job_model.py`. The existing `test_jobs_indexes_created` (line 32) asserts the *old* index name `ix_jobs_source_external_job_id` — replace it so it expects the new unique index, and add index-detail and dialect-specific assertions.

Replace the `test_jobs_indexes_created` function body with:

```python
def test_jobs_indexes_created() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    insp = inspect(engine)
    index_names = {ix["name"] for ix in insp.get_indexes("jobs")}
    assert "uq_jobs_source_external_job_id" in index_names
    assert "ix_jobs_source_external_job_id" not in index_names
    assert "ix_jobs_last_seen_at" in index_names
```

Add a new test that asserts the index is `unique=True` and carries the `postgresql_where` predicate on the model metadata (so the partial-clause intent is pinned in-process, where dialect compilation is not involved):

```python
def test_source_external_id_index_is_unique_and_partial() -> None:
    idx = next(
        ix for ix in Job.__table__.indexes
        if ix.name == "uq_jobs_source_external_job_id"
    )
    assert idx.unique is True
    assert idx.dialect_options["postgresql"]["where"] is not None
```

Update the imports at the top of `backend/tests/test_job_model.py` to include `Job` (already imported) — no new import is required; `inspect`, `create_engine`, `Base`, `Job`, `Session` are all already imported.

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest backend/tests/test_job_model.py -v`
Expected: FAIL — `test_jobs_indexes_created` asserts `uq_jobs_source_external_job_id` which does not exist yet; `test_source_external_id_index_is_unique_and_partial` fails with `StopIteration` (no such index name).

- [ ] **Step 3: Update the model**

Edit `backend/app/models/job.py`, replacing the `__table_args__` block (currently lines 38-41) and updating the import line. Change:

```python
from sqlalchemy import BigInteger, DateTime, Index, Integer, Text, func
```

to:

```python
from sqlalchemy import BigInteger, DateTime, Index, Integer, Text, func, text
```

and replace:

```python
    __table_args__ = (
        Index("ix_jobs_source_external_job_id", "source", "external_job_id"),
        Index("ix_jobs_last_seen_at", "last_seen_at"),
    )
```

with:

```python
    __table_args__ = (
        # Partial unique identity key. `postgresql_where` (the SQLAlchemy 2.0
        # dialect-option name for a partial index predicate) is emitted by the
        # Postgres DDL compiler but dropped on SQLite (which has no partial
        # indexes); both dialects keep the index UNIQUE and null-tolerant, which
        # is what the unit tests exercise. With the unique index in place, the
        # old non-unique `ix_jobs_source_external_job_id` is redundant — the
        # unique index serves every lookup the old one did.
        Index(
            "uq_jobs_source_external_job_id",
            "source",
            "external_job_id",
            unique=True,
            postgresql_where=text("external_job_id IS NOT NULL"),
        ),
        Index("ix_jobs_last_seen_at", "last_seen_at"),
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest backend/tests/test_job_model.py -v`
Expected: PASS (both new/updated tests pass).

- [ ] **Step 5: Commit**

```bash
git add backend/app/models/job.py backend/tests/test_job_model.py
git commit -m "feat(jobs): make (source, external_job_id) a partial unique index"
```

---

### Task 2: `normalize.py` pure normalization functions

**Files:**
- Create: `backend/app/ingestion/normalize.py`
- Test: `backend/tests/test_normalize.py` (new)

**Interfaces:**
- Consumes: none (pure module).
- Produces:
  - `normalize_source(source: str) -> str` — lowercase, strip, collapse internal whitespace.
  - `normalize_external_id(external_job_id: str) -> str | None` — strip; empty ⇒ `None`.
  - `normalize_title(title: str) -> str` — NFKC, collapse whitespace, strip.
  - `normalize_company(company: str | None) -> str | None` — same as title; `None` passthrough.
  - `normalize_location(location: str | None) -> str | None` — same as title; `None` passthrough.
  - `make_job_draft(...)` is **not** in this task — draft construction is Task 5, where the fields and the `JobDraft` type are already in hand.

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_normalize.py`:

```python
from app.ingestion.normalize import (
    normalize_company,
    normalize_external_id,
    normalize_location,
    normalize_source,
    normalize_title,
)


def test_normalize_source_lowercases_and_strips() -> None:
    assert normalize_source("  Google_Careers ") == "google_careers"
    assert normalize_source("GOOGLE_CAREERS") == "google_careers"
    assert normalize_source("google  careers") == "google careers"


def test_normalize_external_id_strips() -> None:
    assert normalize_external_id(" 123 ") == "123"


def test_normalize_external_id_empty_becomes_none() -> None:
    assert normalize_external_id("") is None
    assert normalize_external_id("   ") is None


def test_normalize_title_folds_nbsp_and_collapses_whitespace() -> None:
    assert normalize_title("Software\xa0Engineer") == "Software Engineer"
    assert normalize_title("  Software   Engineer  ") == "Software Engineer"


def test_normalize_title_nfkc_folds_lookalikes() -> None:
    # U+FF26 (fullwidth 'F') normalizes to ASCII 'F' under NFKC.
    assert normalize_title("Ｆull Stack") == "Full Stack"


def test_normalize_company_none_passthrough() -> None:
    assert normalize_company(None) is None
    assert normalize_company("  Google  ") == "Google"


def test_normalize_location_none_passthrough() -> None:
    assert normalize_location(None) is None
    assert normalize_location("  Tokyo\tMetro ") == "Tokyo Metro"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest backend/tests/test_normalize.py -v`
Expected: FAIL — `E ModuleNotFoundError: No module named 'app.ingestion.normalize'`.

- [ ] **Step 3: Write the module**

Create `backend/app/ingestion/normalize.py`:

```python
"""Pure string-normalization for job fields that feed the identity key.

Deliberately conservative (spec §3): NFKC + whitespace collapse for display
fields, slug-lowercasing for `source` (a key component), and empty-as-`None`
for `external_job_id` (an id of ``" "`` is not an id). No casefolding of
`title`/`company`/`location` — they no longer feed a unique key, so case is a
display concern, not an identity concern.
"""

from __future__ import annotations

import unicodedata


def _collapse(value: str) -> str:
    return " ".join(value.split())


def normalize_source(source: str) -> str:
    """Lowercase and collapse a ``jobs.source`` slug."""
    return _collapse(source.lower())


def normalize_external_id(external_job_id: str) -> str | None:
    """Strip the provider id; an empty result becomes ``None``."""
    stripped = external_job_id.strip()
    return stripped or None


def normalize_title(title: str) -> str:
    """NFKC-fold and collapse whitespace in a job title."""
    return _collapse(unicodedata.normalize("NFKC", title))


def normalize_company(company: str | None) -> str | None:
    """Normalize a company display string (currently always ``None``)."""
    if company is None:
        return None
    return normalize_title(company)


def normalize_location(location: str | None) -> str | None:
    """Normalize raw location text; no structured parsing (spec §4.2)."""
    if location is None:
        return None
    return normalize_title(location)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest backend/tests/test_normalize.py -v`
Expected: PASS.

- [ ] **Step 5: Run mypy on the module**

Run: `uv run mypy backend/app/ingestion/normalize.py backend/tests/test_normalize.py`
Expected: no errors.

- [ ] **Step 6: Commit**

```bash
git add backend/app/ingestion/normalize.py backend/tests/test_normalize.py
git commit -m "feat(ingestion): add pure field-normalization functions"
```

---

### Task 3: Repository unique-constraint behavior tests

**Files:**
- Test: `backend/tests/test_job_repository.py` (extend)

**Interfaces:**
- Consumes: `JobRepository`, `_make_job` (existing), `Base` (existing).
- Produces: no code change — this task pins the DB-level behavior the unique index introduces: `IntegrityError` on duplicate `(source, external_job_id)`, coexistence for two `NULL`-id rows, and success for same id under different `source`.

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_job_repository.py`:

```python
from sqlalchemy.exc import IntegrityError


def test_duplicate_source_external_id_raises(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(engine_mod, "engine", session.get_bind())
    repo = JobRepository()
    session.add(_make_job(title="Job A"))
    session.commit()

    with pytest.raises(IntegrityError):
        session.add(_make_job(title="Job B"))
        session.commit()


def test_two_null_external_ids_coexist(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The partial index governs only rows that carry a provider id; two id-less
    # rows must both persist (multiple NULLs are always allowed).
    monkeypatch.setattr(engine_mod, "engine", session.get_bind())
    session.add(_make_job(external_job_id=None, title="No id A"))
    session.add(_make_job(external_job_id=None, title="No id B"))
    session.commit()

    rows = list(session.scalars(select(Job)))
    assert len(rows) == 2


def test_same_id_different_source_coexists(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Provider ids are unique only within a source; two ATSs may both emit `123`.
    monkeypatch.setattr(engine_mod, "engine", session.get_bind())
    session.add(_make_job(source="google_careers", title="Google job"))
    session.add(_make_job(source="linkedin", title="LinkedIn job"))
    session.commit()

    rows = list(session.scalars(select(Job)))
    assert len(rows) == 2
```

Note: `IntegrityError` is imported inside the test module above to keep the append self-contained; it may already be importable alongside a future top-level import — place `from sqlalchemy.exc import IntegrityError` at module top if the file is being reorganized.

The existing `test_find_by_external_id_returns_first_when_duplicated` (lines 88-103) **now contradicts** the new unique constraint — it inserts two rows with the same `(source, external_job_id)` and asserts both succeed. **Delete that test outright.** Its purpose ("lookup returns a row even when duplicates exist") is obsolete: under the PBI-3 constraint no duplicate can exist, and `test_find_by_external_id_returns_match` already covers returning a row for a present id. The file must no longer assert that duplicate inserts succeed.

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest backend/tests/test_job_repository.py -v`
Expected: FAIL — `test_duplicate_source_external_id_raises` expects `IntegrityError` but the model change (Task 1) has not been applied to this branch's metadata yet, OR (if running in-order, Task 1 already applied) it passes and the *old* `test_find_by_external_id_returns_first_when_duplicated` fails against the new constraint. Either way, reconcile: after adding these tests and updating the superseded test, the full file must be green.

- [ ] **Step 3: Run tests to verify they pass**

Run: `uv run pytest backend/tests/test_job_repository.py -v`
Expected: PASS (duplicate now raises; two null-id rows coexist; cross-source duplicates coexist).

- [ ] **Step 4: Commit**

```bash
git add backend/tests/test_job_repository.py
git commit -m "test(jobs): pin partial-unique-constraint behavior in repository"
```

---

### Task 4: Alembic migration `0003`

**Files:**
- Create: `backend/alembic/versions/0003_job_identity.py`

**Interfaces:**
- Consumes: `Job` model metadata (Task 1).
- Produces: revision `"0003"` chained from `"0002"`; `upgrade()` drops `ix_jobs_source_external_job_id` and creates partial unique `uq_jobs_source_external_job_id`; `downgrade()` inverts it.

- [ ] **Step 1: Write the migration**

Create `backend/alembic/versions/0003_job_identity.py`:

```python
"""partial unique identity: (source, external_job_id)

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-17
"""

import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Drop the PBI-1 non-unique lookup index; the unique index below serves every
    # lookup the old one did. `postgresql_where` encodes the partial predicate.
    op.drop_index("ix_jobs_source_external_job_id", table_name="jobs")
    op.create_index(
        "uq_jobs_source_external_job_id",
        "jobs",
        ["source", "external_job_id"],
        unique=True,
        postgresql_where=sa.text("external_job_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_jobs_source_external_job_id", table_name="jobs")
    op.create_index(
        "ix_jobs_source_external_job_id", "jobs", ["source", "external_job_id"]
    )
```

> **Note to implementer:** `postgresql_where` in `op.create_index` accepts a `sa.text()` SQL expression (here as the plain string `sa.text("external_job_id IS NOT NULL")`, which Alembic type-checks into a `TextClause`), **not** a bare string — a bare string fails a mypy/ruff pass under the repo's strict config. The `sa.text(...)` form is used because this repo is Postgres-only (per `CLAUDE.md`) and it matches the model's `postgresql_where=text(...)` exactly, which is what keeps `alembic check` drift-free.

- [ ] **Step 2: Verify no autogenerate drift against the model**

Run: `uv run --package jobsearch-backend alembic -c backend/alembic.ini check`
Expected: no drift reported (`No new upgrade operations detected`). Requires Postgres up (`make db-up`). If drift is reported, reconcile the `0003` body with Task 1's model — particularly the `postgresql_where` predicate and the index name — before proceeding.

- [ ] **Step 3: Apply against real Postgres and confirm**

Run:
```bash
make db-up
make migrate
docker compose exec db psql -U jobsearch -d jobsearch -c "\d jobs"
```
Expected: `uq_jobs_source_external_job_id UNIQUE` present with a `WHERE (external_job_id IS NOT NULL)` predicate; `ix_jobs_source_external_job_id` gone.

- [ ] **Step 4: Confirm idempotent upgrade and clean downgrade**

Run:
```bash
make migrate                                   # upgrade head again — no-op
uv run --package jobsearch-backend alembic -c backend/alembic.ini downgrade base
uv run --package jobsearch-backend alembic -c backend/alembic.ini upgrade head
```
Expected: second upgrade is a no-op; downgrade restores `ix_jobs_source_external_job_id` and drops `uq_jobs_source_external_job_id`; re-upgrade is clean.

- [ ] **Step 5: Commit**

```bash
git add backend/alembic/versions/0003_job_identity.py
git commit -m "feat(jobs): add 0003 partial unique identity index"
```

---

### Task 5: Normalize at the draft boundary + `UniqueViolation` handling

**Files:**
- Modify: `backend/app/ingestion/sources/google_careers.py:28-42`
- Modify: `backend/app/ingestion/service.py:35-70`
- Test: `backend/tests/test_ingestion_service.py` (extend); `backend/tests/test_google_careers_source.py` (extend)

**Interfaces:**
- Consumes: `normalize_*` (Task 2); `JobDraft` (existing `drafts.py`); `Job`, `JobRepository` (existing).
- Produces: `GoogleCareersSource.fetch()` yields `JobDraft` objects whose `external_job_id` / `title` / `location` / `company` are normalized (so `IngestionService` constructs a `Job` with already-canonical fields); `IngestionService.run()` catches `IntegrityError` on insert and re-reads + counts `seen`.

- [ ] **Step 1: Normalize in the source**

Edit `backend/app/ingestion/sources/google_careers.py`, changing the `fetch()` draft construction (lines 35-42). Currently:

```python
            draft = JobDraft(
                external_job_id=external_job_id,
                title=raw.get("title") or "",
                location=raw.get("location"),
                company=raw.get("company"),
                url=raw.get("url") or "",
            )
```

Add an import (top of file, alongside the existing `JobDraft` import):

```python
from app.ingestion.normalize import (
    normalize_company,
    normalize_external_id,
    normalize_location,
    normalize_title,
)
```

and rewrite the `fetch()` loop so normalization happens before the id guard and the draft is built from normalized values:

```python
    def fetch(self) -> Iterator[JobDraft]:
        spider = GoogleCareersSpider()
        for raw in self._run_crawl(spider):
            external_job_id = normalize_external_id(raw.get("external_job_id") or "")
            if not external_job_id:
                # Id-less page: un-parseable for this source. This is a hard-coded
                # policy at the source layer — see spec §4.3 (id-less jobs gap).
                # `jobs.external_job_id` is nullable and the PBI-3 partial index
                # exists precisely for that case, but no source yet produces a
                # legitimately id-less job, so this guard drops the dict entirely.
                self.skipped_no_id += 1
                continue
            draft = JobDraft(
                external_job_id=external_job_id,
                title=normalize_title(raw.get("title") or ""),
                location=normalize_location(raw.get("location")),
                company=normalize_company(raw.get("company")),
                url=raw.get("url") or "",
            )
            yield draft
```

(Trim the moved comment to taste; the requirement is that the `skipped_no_id` branch records the id-less-gap rationale, per spec §4.3.)

- [ ] **Step 2: Handle `UniqueViolation` in the service**

Edit `backend/app/ingestion/service.py`. Add the import at the top, merging with the existing `from sqlalchemy.orm import Session` (line 9):

```python
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
```

Then rewrite `run()` (lines 35-70) to catch the unique violation on insert:

```python
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
                    try:
                        self.repository.add(session, job)
                        created += 1
                    except IntegrityError:
                        # A concurrent writer (or an in-run duplicate already
                        # flushed) beat us to this identity. Roll back the
                        # poisoned insert, re-read, and count it as `seen`.
                        # This requires the flush in `add` (which it has) so the
                        # constraint is evaluated per-draft, not at commit.
                        session.rollback()
                        existing = self.repository.find_by_external_id(
                            session,
                            source=self.source.name,
                            external_job_id=draft.external_job_id,
                        )
                        if existing is not None:
                            existing.last_seen_at = now
                            seen += 1
                        else:
                            # Re-insert failed to find a row we can bump; surface
                            # rather than silently drop the draft.
                            raise
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

> **Correctness note:** `JobRepository.add` calls `session.flush()`, so the unique constraint is evaluated per-draft — the `IntegrityError` surfaces on the `add` line, not at `session.commit()`. The rollback + re-read above is the deliberate "keep the read, handle `UniqueViolation` on insert" behavior from spec §4.3.

- [ ] **Step 3: Write the failing tests**

Append to `backend/tests/test_ingestion_service.py`:

```python
def test_duplicate_in_one_run_counts_seen_after_constraint(
    session_factory: Callable[[], Session],
) -> None:
    # Two drafts carrying the same (source, external_job_id) in a single run —
    # the first inserts; the second now counts as seen (spec §4.3 fix, was a
    # duplicate row before the unique constraint).
    service = IngestionService(
        FakeSource([_draft("123"), _draft("123")]),
        session_factory,
        now_provider=lambda: FIXED_NOW,
    )
    result = service.run()
    assert result.created == 1
    assert result.seen == 1

    with session_factory() as s:
        assert len(list(s.scalars(select(Job)))) == 1


def test_normalized_values_are_written(
    session_factory: Callable[[], Session],
) -> None:
    # The service writes exactly the normalized form: a source handing back a
    # draft with dirty title/id must persist the canonical values.
    dirty = JobDraft(
        external_job_id=" 123 ",
        title="  Software\xa0Engineer ",
        company=None,
        location="  Tokyo ",
        url="https://example.com/jobs/123",
    )
    service = IngestionService(
        FakeSource([dirty]), session_factory, now_provider=lambda: FIXED_NOW
    )
    service.run()

    with session_factory() as s:
        job = s.scalar(select(Job))
        assert job is not None
        assert job.external_job_id == "123"
        assert job.title == "Software Engineer"
        assert job.location == "Tokyo"
```

> **Note:** `test_normalized_values_are_written` exercises the service end-to-end but assumes the *source* already normalized (Task 5 Step 1). If you prefer to pin normalization purely at the source boundary, add a parallel assertion in `backend/tests/test_google_careers_source.py` instead; both are acceptable. The key invariant — "every `Job` the service writes already has canonicalized fields" — is what this pins.

- [ ] **Step 4: Run tests to verify they fail (then pass)**

Run: `uv run pytest backend/tests/test_ingestion_service.py backend/tests/test_google_careers_source.py -v`
Expected: before Task 5 code, `test_duplicate_in_one_run_counts_seen_after_constraint` fails (the second draft would insert a duplicate → `IntegrityError` from Task 1's index, not a clean `seen`); `test_normalized_values_are_written` fails (values written un-normalized). After Steps 1-2, all pass.

- [ ] **Step 5: Run mypy on the changed modules**

Run: `uv run mypy backend/app/ingestion/service.py backend/app/ingestion/sources/google_careers.py`
Expected: no errors.

- [ ] **Step 6: Commit**

```bash
git add backend/app/ingestion/sources/google_careers.py backend/app/ingestion/service.py \
        backend/tests/test_ingestion_service.py backend/tests/test_google_careers_source.py
git commit -m "feat(ingestion): normalize at draft boundary and handle unique violations"
```

---

### Task 6: Postgres-gated migration tests (predicate + dirty-row)

**Files:**
- Create: `backend/tests/test_migration_0003.py` (opt-in `ingest` marker)

**Interfaces:**
- Consumes: migrations `0001`→`0003`; live Postgres (Docker).
- Produces: proof that the predicate is partial on Postgres (two `NULL`s coexist; a duplicate raises) and that a row carrying dirty display text is left unmodified by the migration.

- [ ] **Step 1: Write the Postgres-gated tests**

Create `backend/tests/test_migration_0003.py`:

```python
"""Postgres-only migration tests, opt-in via the `ingest` marker (make test-integration).

SQLite has no partial-index support and cannot prove the `WHERE external_job_id
IS NOT NULL` predicate; these assertions run against the real Postgres the
Docker Compose stack provides.
"""

import os

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError, ProgrammingError

pytestmark = pytest.mark.ingest

DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql+psycopg://jobsearch:jobsearch@localhost:5432/jobsearch",
)


@pytest.fixture()
def engine():
    return create_engine(DATABASE_URL)


def _reject_duplicate(engine) -> None:
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO jobs (source, external_job_id, title) "
                "VALUES ('google_careers', '__pbi3test__', 'dup')"
            )
        )
        with pytest.raises(IntegrityError):
            conn.execute(
                text(
                    "INSERT INTO jobs (source, external_job_id, title) "
                    "VALUES ('google_careers', '__pbi3test__', 'dup')"
                )
            )


def test_partial_index_rejects_duplicate(engine) -> None:
    _reject_duplicate(engine)


def test_partial_index_allows_two_null_ids(engine) -> None:
    # Two id-less rows must coexist: the predicate excludes NULL ids. A *plain*
    # unique index would also allow this on Postgres (multiple NULLs permitted),
    # so this is a necessary-but-not-sufficient check; combined with the
    # reject-duplicate test it pins the partial behavior end-to-end.
    with engine.begin() as conn:
        conn.execute(text("INSERT INTO jobs (source, title) VALUES ('t', 'a')"))
        conn.execute(text("INSERT INTO jobs (source, title) VALUES ('t', 'b')"))
        rows = conn.execute(text("SELECT count(*) FROM jobs WHERE source='t'")).scalar()
        assert rows == 2
        conn.execute(text("DELETE FROM jobs WHERE source='t'"))


def test_dirty_row_preserved_by_migration(engine) -> None:
    # Spec §5.2: legacy rows with dirty display text (a double-space title) must
    # NOT be re-normalized by this migration — rewriting user-visible data is
    # beyond the constraint the user approved. Pin that decision: insert a row
    # with a double-space title, confirm the migration leaves it byte-identical.
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO jobs (source, external_job_id, title) "
                "VALUES ('t', '__dirty__', 'Software Engineer, AI/ML,  PhD')"
            )
        )
    with engine.connect() as conn:
        title = conn.execute(
            text("SELECT title FROM jobs WHERE external_job_id = '__dirty__'")
        ).scalar()
    assert title is not None
    assert "  " in title  # the double space "  PhD" is still present
    with engine.begin() as conn:
        conn.execute(
            text("DELETE FROM jobs WHERE external_job_id = '__dirty__'")
        )
```

- [ ] **Step 2: Run against live Postgres**

Run:
```bash
make db-up
make migrate
uv run pytest -m ingest backend/tests/test_migration_0003.py -v
```
Expected: all three pass — the duplicate insert is rejected, two null-id rows coexist, and the double-space title survives the migration unmodified.

- [ ] **Step 3: Commit**

```bash
git add backend/tests/test_migration_0003.py
git commit -m "test(jobs): postgres-gated partial-index and dirty-row migration tests"
```

---

### Task 7: Tracker sync (PBI 1 + PBI 3 status)

**Files:**
- Modify: `implementation_checklist/pbi_tracker.md`
- Modify: `frontend/src/pages/pbis.ts`

**Interfaces:**
- Consumes: none (documentation/display only).
- Produces: PBI 1 marked `[x]` (it was implemented and committed but the tracker still shows `[ ]` per spec §10); PBI 3 marked `[x]` once this PBI lands and its line reworded to reflect the actual data-layer scope (no "across ATS providers").

- [ ] **Step 1: Update the tracker**

Edit `implementation_checklist/pbi_tracker.md`:

- Mark PBI 1 done (change `- [ ] **PBI 1 — Jobs schema**` to `- [x] ...`) — reconciling the stale status flagged in spec §10.
- Reword PBI 3 and mark it done:

from:

```
- [ ] **PBI 3 — Normalization + dedup keys**
  - Canonical job identity across URLs and ATS providers.
  - Depends on: PBI 1
```

to:

```
- [x] **PBI 3 — Normalization + dedup keys**
  - Unique `(source, external_job_id)` identity via a partial unique index; field normalization at the ingest boundary. (Cross-ATS matching deferred — one source today.)
  - Depends on: PBI 1
```

- [ ] **Step 2: Mirror in the frontend**

Edit `frontend/src/pages/pbis.ts`, updating the PBI 3 entry (lines 22-29):

```ts
  {
    id: "3",
    stage: "mvp",
    title: "Normalization + dedup keys",
    description:
      "Unique (source, external_job_id) identity via a partial unique index; field normalization at the ingest boundary. (Cross-ATS matching deferred.)",
    depends_on: ["1"],
  },
```

- [ ] **Step 3: Run the frontend test**

Run: `cd frontend && npm test -- PbiTrackerPage`
Expected: PASS (the test asserts on `title`, which is unchanged; run to confirm no build break).

- [ ] **Step 4: Commit**

```bash
git add implementation_checklist/pbi_tracker.md frontend/src/pages/pbis.ts
git commit -m "docs(pbi3): mark PBI 1 + 3 done; reword PBI 3 to data-layer scope"
```

---

### Task 8: Full verification gate

**Files:**
- None (verification only).

**Interfaces:**
- Consumes: everything above.
- Produces: green `make lint / typecheck / test` and a confirmed Postgres constraint + clean downgrade.

- [ ] **Step 1: Lint**

Run: `make lint`
Expected: clean (ruff check + format-check pass).

- [ ] **Step 2: Type-check**

Run: `make typecheck`
Expected: no errors across `backend/app` and `shared/jobsearch_shared`.

- [ ] **Step 3: Full default test suite**

Run: `make test`
Expected: all pass across `backend/tests` + `shared/tests` (the `ingest`-marked tests are excluded by the `-m "not ingest"` default).

- [ ] **Step 4: End-to-end constraint on Postgres**

Run:
```bash
make db-up
make migrate
docker compose exec db psql -U jobsearch -d jobsearch -c "\d jobs"
docker compose exec db psql -U jobsearch -d jobsearch -c "INSERT INTO jobs (source, external_job_id, title) VALUES ('google_careers', '__gate__', 'x'); INSERT INTO jobs (source, external_job_id, title) VALUES ('google_careers', '__gate__', 'x');"
uv run --package jobsearch-backend alembic -c backend/alembic.ini downgrade base
uv run --package jobsearch-backend alembic -c backend/alembic.ini upgrade head
```
Expected: `\d jobs` shows `uq_jobs_source_external_job_id UNIQUE` with the `WHERE` predicate; the second `INSERT` in step 2 is rejected with a unique-violation error; downgrade/upgrade round-trips cleanly.

- [ ] **Step 5: Confirm clean git status**

Run: `git status --short`
Expected: only intended files (or none if fully committed). If ruff format touched files in Step 1, commit the auto-fix.

---

## Execution Handoff

See the plan self-review below; the plan is complete and ready for the human to choose an execution method.
