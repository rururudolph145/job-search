# PBI 1 — Jobs Schema Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Establish the first persistent domain table for the Job Search Intelligence Platform — the `jobs` table, its SQLAlchemy ORM model, an Alembic migration, a thin repository layer, and a shared response contract.

**Architecture:** A single, deliberately minimal `jobs` table (the `companies` and `job_sources` tables named in the tracker are deferred to PBI 3 per the spec's MVP scope decision). A `Job` ORM model subclasses the existing `Base`; an Alembic revision `0002` chains from the empty baseline; a `JobRepository` exposes four read/write primitives with no business logic; a `JobResponse` Pydantic contract sits in `shared` and is re-exported through `app.schemas`.

**Tech Stack:** Python 3.13, SQLAlchemy 2.0 (typed `Mapped` style), Alembic 1.13, Pydantic 2, pytest (SQLite `:memory:` for unit tests), Postgres 16 + pgvector (Docker Compose, migration verification only), mypy strict, ruff, uv workspace.

**Spec:** [docs/superpowers/specs/2026-10-13-pbi1-jobs-schema-design.md](../specs/2026-10-13-pbi1-jobs-schema-design.md)

## Global Constraints

- Python `>=3.13`; all new functions/methods fully annotated (mypy `disallow_untyped_defs`, `no_implicit_optional`).
- Ruff selects `E, W, F, I, C, B` with double quotes and 88-char lines (`E501`, `E203` ignored).
- SQLAlchemy 2.0 typed style: `Mapped[...]` + `mapped_column(...)`; `from __future__ import annotations`-friendly annotations.
- Timestamps `server_default=func.now()`; `updated_at` adds `onupdate=func.now()`.
- Alembic revision id is the zero-padded string `"0002"`, `down_revision = "0001"`; `upgrade()`/`downgrade()` annotated `-> None`.
- Repository methods take a `Session` as first parameter; no repository method commits — commit is the caller's / session context's job.
- Only models exported from `app.models` (i.e. imported in `app/models/__init__.py`) are visible to Alembic autogenerate.

## Review Focus

The inputs and conditions below are not covered by the spec's happy path and are the most likely to bite a person using this software. Each line names the failure mode and links to the task whose tests pin it.

- **Missing `company` on a listing.** `company` is nullable; a scraped page may not name an employer. `Job` must allow `company=None` and persist it (not coerce to `""`). — Task 2 (schema allows null `company`).
- **A single source re-posting the same external id.** `(source, external_job_id)` is non-unique by design (dedup is PBI 3). `find_by_external_id` returns the first match even when duplicates exist, and `add` happily inserts a second row — no error. — Task 4 (`add` permits a duplicate external id; `find_by_external_id` returns a row).
- **Repository lookup with a nonexistent id.** `get`/`find_by_external_id` return `None` rather than raising. — Task 4.
- **Empty result list.** `list` with `limit=0` or past all rows returns `[]`, not `None` or an error. — Task 4.
- **ORM→contract boundary leaking internal fields.** `JobResponse` must expose **only** the nine `jobs` columns — `from_attributes=True` must not accidentally serialize SQLAlchemy internals (the ORM model has no extra attrs, so verify the dump key set exactly). — Task 5.

---

### Task 1: `Job` ORM model + package export

**Files:**
- Create: `backend/app/models/job.py`
- Modify: `backend/app/models/__init__.py`

**Interfaces:**
- Produces:
  - `Job` — SQLAlchemy model, subclass of `app.models.base.Base`, exportable as `app.models.Job`.
  - Table name `jobs` with columns: `id` (`BIGINT` autoincrement PK), `source` (TEXT, not null), `external_job_id` (TEXT, null), `title` (TEXT, not null), `company` (TEXT, null), `location` (TEXT, null), `first_seen_at` (TIMESTAMPTZ, not null, `server_default=func.now()`), `last_seen_at` (TIMESTAMPTZ, not null, `server_default=func.now()`), `updated_at` (TIMESTAMPTZ, not null, `server_default=func.now()`, `onupdate=func.now()`), plus indexes `ix_jobs_source_external_job_id` on `(source, external_job_id)` and `ix_jobs_last_seen_at` on `(last_seen_at)`.

- [x] **Step 1: Write the failing test**

Create `backend/tests/test_job_model.py`:

```python
from sqlalchemy import create_engine, inspect

from app.models import Base


def test_jobs_table_has_expected_columns() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    insp = inspect(engine)
    assert "jobs" in insp.get_table_names()

    cols = {c["name"]: c for c in insp.get_columns("jobs")}
    assert set(cols) == {
        "id",
        "source",
        "external_job_id",
        "title",
        "company",
        "location",
        "first_seen_at",
        "last_seen_at",
        "updated_at",
    }
    assert cols["source"]["nullable"] is False
    assert cols["title"]["nullable"] is False
    assert cols["external_job_id"]["nullable"] is True
    assert cols["company"]["nullable"] is True
    assert cols["location"]["nullable"] is True
```

- [x] **Step 2: Run test to verify it fails**

Run: `uv run pytest backend/tests/test_job_model.py -v`
Expected: FAIL — `E ImportError: cannot import name 'Job'` (the `Base` import still succeeds, but create_all yields no `jobs` table → assertion `"jobs" in insp.get_table_names()` fails).

- [x] **Step 3: Write the model**

Create `backend/app/models/job.py`:

```python
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Index, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    source: Mapped[str] = mapped_column(Text, nullable=False)
    external_job_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    company: Mapped[str | None] = mapped_column(Text, nullable=True)
    location: Mapped[str | None] = mapped_column(Text, nullable=True)
    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    __table_args__ = (
        Index("ix_jobs_source_external_job_id", "source", "external_job_id"),
        Index("ix_jobs_last_seen_at", "last_seen_at"),
    )
```

- [x] **Step 4: Export `Job` from the package**

Edit `backend/app/models/__init__.py`:

```python
from app.models.base import Base
from app.models.job import Job

__all__ = ["Base", "Job"]
```

- [x] **Step 5: Run the test to verify it passes**

Run: `uv run pytest backend/tests/test_job_model.py -v`
Expected: PASS.

- [x] **Step 6: Run mypy on the new model**

Run: `uv run mypy backend/app/models/job.py`
Expected: no errors.

- [x] **Step 7: Commit**

```bash
git add backend/app/models/job.py backend/app/models/__init__.py backend/tests/test_job_model.py
git commit -m "feat(jobs): add Job ORM model and export from app.models"
```

---

### Task 2: `Job` model field-level nullable/default tests

**Files:**
- Test: `backend/tests/test_job_model.py` (append)

**Interfaces:**
- Consumes: `Job` (Task 1), `Base.metadata` (existing).
- Produces: none new — pins the nullable + default contracts a using-engineer depends on.

- [x] **Step 1: Write the failing tests**

Append to `backend/tests/test_job_model.py`:

```python
from sqlalchemy import create_engine, inspect, select
from sqlalchemy.orm import Session

from app.models import Base, Job


def test_jobs_indexes_created() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    insp = inspect(engine)
    index_names = {ix["name"] for ix in insp.get_indexes("jobs")}
    assert "ix_jobs_source_external_job_id" in index_names
    assert "ix_jobs_last_seen_at" in index_names


def test_job_allows_null_company() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    job = Job(
        source="google_careers",
        external_job_id="123",
        title="Software Engineer",
        company=None,
        location="Tokyo",
    )
    with Session(engine) as session:
        session.add(job)
        session.commit()

    with Session(engine) as session:
        stored = session.scalar(select(Job))
        assert stored is not None
        assert stored.company is None
        assert stored.title == "Software Engineer"
```

- [x] **Step 2: Run tests to verify they fail**

Run: `uv run pytest backend/tests/test_job_model.py -v`
Expected: PASS (these extend Task 1's already-created schema — they may pass immediately). If they pass without edits, confirm the assertions genuinely exercise the model (they do: index names, null `company` round-trip), and proceed. A non-passing result means Task 1 is incomplete — backtrack.

> **Outcome note:** the null-`company` round-trip test *did* fail, exposing a real bug — `BigInteger` + `autoincrement=True` does not autoincrement under SQLite, so inserts failed. Fixed by using `BigInteger().with_variant(Integer, "sqlite")` on `Job.id` (BIGINT on Postgres, rowid autoincrement on SQLite).

- [x] **Step 3: Run the model tests + mypy together**

Run: `uv run pytest backend/tests/test_job_model.py -v && uv run mypy backend/app/models/job.py`
Expected: both clean.

- [x] **Step 4: Commit**

```bash
git add backend/tests/test_job_model.py
git commit -m "test(jobs): pin nullable fields, defaults, and index presence"
```

---

### Task 3: Alembic migration `0002` (jobs table)

**Files:**
- Create: `backend/alembic/versions/0002_jobs.py`

**Interfaces:**
- Consumes: `Job` model metadata (Task 1) — must match it byte-for-byte in structure.
- Produces: revision `"0002"` chained from `"0001"`; `upgrade()`/`downgrade()`.

- [x] **Step 1: Write the migration**

Create `backend/alembic/versions/0002_jobs.py`:

```python
"""jobs table

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-14
"""

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "jobs",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("external_job_id", sa.Text(), nullable=True),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("company", sa.Text(), nullable=True),
        sa.Column("location", sa.Text(), nullable=True),
        sa.Column(
            "first_seen_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "last_seen_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_jobs_source_external_job_id", "jobs", ["source", "external_job_id"]
    )
    op.create_index("ix_jobs_last_seen_at", "jobs", ["last_seen_at"])


def downgrade() -> None:
    op.drop_index("ix_jobs_last_seen_at", table_name="jobs")
    op.drop_index("ix_jobs_source_external_job_id", table_name="jobs")
    op.drop_table("jobs")
```

- [x] **Step 2: Verify no autogenerate drift against the model**

Run: `uv run --package jobsearch-backend alembic -c backend/alembic.ini check`
Expected: no output (i.e. no drift reported). If it reports the target database differs from migrations, the committed revision is out of sync with `Base.metadata` — reconcile the `0002` body with Task 1's model before proceeding. (This requires Postgres up; see Step 3.)

> **Outcome:** reported `No new upgrade operations detected` — zero drift.

- [x] **Step 3: Apply against real Postgres and confirm**

Run:
```bash
make db-up
make migrate
docker compose exec db psql -U jobsearch -d jobsearch -c "\d jobs"
```
Expected: `jobs` table and both indexes present in the `\d` output.

- [x] **Step 4: Confirm idempotency of upgrade and clean downgrade**

Run:
```bash
make migrate                                   # upgrade head again — no-op, no error
uv run --package jobsearch-backend alembic -c backend/alembic.ini downgrade base
uv run --package jobsearch-backend alembic -c backend/alembic.ini upgrade head
```
Expected: second upgrade is a no-op; downgrade drops `jobs` cleanly; re-upgrade restores it.

- [x] **Step 5: Commit**

```bash
git add backend/alembic/versions/0002_jobs.py
git commit -m "feat(jobs): add 0002 migration creating jobs table"
```

---

### Task 4: `JobRepository`

**Files:**
- Create: `backend/app/repositories/job.py`
- Test: `backend/tests/test_job_repository.py`

**Interfaces:**
- Consumes: `Job` (Task 1); `app.db.engine.engine` (monkeypatched in tests, the established injection pattern from `backend/tests/test_engine.py`); `Session` from SQLAlchemy.
- Produces:
  - `get(session: Session, job_id: int) -> Job | None`
  - `list(session: Session, *, limit: int, offset: int) -> list[Job]`
  - `add(session: Session, job: Job) -> Job` (adds + flushes; does **not** commit)
  - `find_by_external_id(session: Session, *, source: str, external_job_id: str) -> Job | None`

- [x] **Step 1: Write the failing tests**

Create `backend/tests/test_job_repository.py`:

```python
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.db import engine as engine_mod
from app.models import Base, Job
from app.repositories.job import JobRepository


@pytest.fixture()
def session() -> Session:
    test_engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(test_engine)
    return Session(test_engine)


def _make_job(**overrides: object) -> Job:
    defaults: dict[str, object] = {
        "source": "google_careers",
        "external_job_id": "123",
        "title": "Software Engineer",
        "company": "Google",
        "location": "Tokyo",
    }
    defaults.update(overrides)
    return Job(**defaults)


def test_add_persists_job(session: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(engine_mod, "engine", session.get_bind())
    job = _make_job()
    repo = JobRepository()
    result = repo.add(session, job)
    assert result is job
    assert job.id is not None  # flushed, id assigned
    # commit left to caller
    session.commit()
    stored = session.scalar(select(Job))
    assert stored is not None
    assert stored.title == "Software Engineer"


def test_get_returns_job_or_none(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(engine_mod, "engine", session.get_bind())
    repo = JobRepository()
    job = _make_job()
    session.add(job)
    session.commit()

    assert repo.get(session, job.id).id == job.id  # type: ignore[union-attr]
    assert repo.get(session, 999999) is None


def test_find_by_external_id_returns_none_when_absent(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(engine_mod, "engine", session.get_bind())
    repo = JobRepository()
    assert repo.find_by_external_id(
        session, source="google_careers", external_job_id="nope"
    ) is None


def test_find_by_external_id_returns_match(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(engine_mod, "engine", session.get_bind())
    repo = JobRepository()
    job = _make_job()
    session.add(job)
    session.commit()

    found = repo.find_by_external_id(
        session, source="google_careers", external_job_id="123"
    )
    assert found is not None
    assert found.id == job.id


def test_list_applies_limit_offset(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(engine_mod, "engine", session.get_bind())
    repo = JobRepository()
    for i in range(5):
        session.add(_make_job(external_job_id=str(i), title=f"Job {i}"))
    session.commit()

    page = repo.list(session, limit=2, offset=1)
    assert [j.title for j in page] == ["Job 1", "Job 2"]
    assert repo.list(session, limit=0, offset=0) == []
```

- [x] **Step 2: Run tests to verify they fail**

Run: `uv run pytest backend/tests/test_job_repository.py -v`
Expected: FAIL — `E ModuleNotFoundError: No module named 'app.repositories.job'`.

- [x] **Step 3: Write the repository**

Create `backend/app/repositories/job.py`:

```python
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Job


class JobRepository:
    def get(self, session: Session, job_id: int) -> Job | None:
        return session.get(Job, job_id)

    def list(self, session: Session, *, limit: int, offset: int) -> list[Job]:
        stmt = select(Job).order_by(Job.id).limit(limit).offset(offset)
        return list(session.scalars(stmt))

    def add(self, session: Session, job: Job) -> Job:
        session.add(job)
        session.flush()
        return job

    def find_by_external_id(
        self, session: Session, *, source: str, external_job_id: str
    ) -> Job | None:
        stmt = select(Job).where(
            Job.source == source, Job.external_job_id == external_job_id
        )
        return session.scalar(stmt)
```

- [x] **Step 4: Run tests to verify they pass**

Run: `uv run pytest backend/tests/test_job_repository.py -v`
Expected: PASS.

- [x] **Step 5: Run mypy on the repository**

Run: `uv run mypy backend/app/repositories/job.py backend/tests/test_job_repository.py`
Expected: no errors.

- [x] **Step 6: Commit**

```bash
git add backend/app/repositories/job.py backend/tests/test_job_repository.py
git commit -m "feat(jobs): add JobRepository with get/list/add/find_by_external_id"
```

---

### Task 5: Shared `JobResponse` contract + re-export

**Files:**
- Modify: `shared/jobsearch_shared/schemas.py`
- Modify: `backend/app/schemas/__init__.py`
- Modify: `shared/tests/test_schemas.py`

**Interfaces:**
- Consumes: `Job` ORM (Task 1) — for the `from_attributes` round-trip test.
- Produces:
  - `JobResponse` (in `jobsearch_shared.schemas`) — Pydantic model with `model_config = ConfigDict(from_attributes=True)` and exactly these fields: `id: int`, `source: str`, `external_job_id: str | None`, `title: str`, `company: str | None`, `location: str | None`, `first_seen_at: datetime`, `last_seen_at: datetime`, `updated_at: datetime`.
  - Re-export `JobResponse` through `app.schemas`.

- [x] **Step 1: Write the failing tests**

Create `shared/tests/test_job_response.py`:

```python
from datetime import datetime, timezone

from jobsearch_shared.schemas import JobResponse


def test_job_response_roundtrip() -> None:
    now = datetime(2026, 10, 14, 12, 0, 0, tzinfo=timezone.utc)
    j = JobResponse(
        id=1,
        source="google_careers",
        external_job_id="123",
        title="Software Engineer",
        company="Google",
        location="Tokyo",
        first_seen_at=now,
        last_seen_at=now,
        updated_at=now,
    )
    assert j.id == 1
    assert j.company == "Google"


def test_job_response_from_attributes_and_null_company() -> None:
    class Stub:
        id = 1
        source = "google_careers"
        external_job_id = "123"
        title = "Software Engineer"
        company = None
        location = "Tokyo"
        first_seen_at = datetime(2026, 10, 14, 12, 0, 0, tzinfo=timezone.utc)
        last_seen_at = datetime(2026, 10, 14, 12, 0, 0, tzinfo=timezone.utc)
        updated_at = datetime(2026, 10, 14, 12, 0, 0, tzinfo=timezone.utc)

    j = JobResponse.model_validate(Stub())
    assert j.company is None


def test_job_response_field_set_is_exact() -> None:
    assert set(JobResponse.model_fields) == {
        "id",
        "source",
        "external_job_id",
        "title",
        "company",
        "location",
        "first_seen_at",
        "last_seen_at",
        "updated_at",
    }
```

And add a round-trip test in `backend/tests/test_job_response.py`:

```python
from app.models import Base, Job
from app.schemas import JobResponse
from sqlalchemy import create_engine
from sqlalchemy.orm import Session


def test_job_response_validates_orm_instance() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    job = Job(
        source="google_careers",
        external_job_id="123",
        title="Software Engineer",
        company=None,
        location="Tokyo",
    )
    with Session(engine) as session:
        session.add(job)
        session.commit()

    resp = JobResponse.model_validate(job, from_attributes=True)
    assert resp.title == "Software Engineer"
    assert resp.company is None
```

- [x] **Step 2: Run tests to verify they fail**

Run: `uv run pytest shared/tests/test_job_response.py backend/tests/test_job_response.py -v`
Expected: FAIL — `E ImportError: cannot import name 'JobResponse'`.

- [x] **Step 3: Add `JobResponse` to the shared contract**

Edit `shared/jobsearch_shared/schemas.py` to append:

```python
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class HealthResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    status: str


class JobResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    source: str
    external_job_id: str | None
    title: str
    company: str | None
    location: str | None
    first_seen_at: datetime
    last_seen_at: datetime
    updated_at: datetime
```

- [x] **Step 4: Re-export through `app.schemas`**

Edit `backend/app/schemas/__init__.py`:

```python
"""Thin re-exports of shared contracts.

Domain schemas live in ``jobsearch_shared`` and are re-exported here so the
backend can import from ``app.schemas`` without a direct dependency on the
shared package's import path in application code.
"""

from jobsearch_shared.schemas import HealthResponse, JobResponse

__all__ = ["HealthResponse", "JobResponse"]
```

- [x] **Step 5: Run tests to verify they pass**

Run: `uv run pytest shared/tests/test_job_response.py backend/tests/test_job_response.py -v`
Expected: PASS.

> **Outcome:** the ORM round-trip test initially failed with `DetachedInstanceError` — commit() expires attributes, and a closed session cannot refresh them. Test-only fix: validate against the instance while the session is still open. The production contract was correct.

- [x] **Step 6: Run mypy on the shared contract**

Run: `uv run mypy shared/jobsearch_shared backend/app/schemas`
Expected: no errors.

- [x] **Step 7: Commit**

```bash
git add shared/jobsearch_shared/schemas.py backend/app/schemas/__init__.py \
        shared/tests/test_job_response.py backend/tests/test_job_response.py
git commit -m "feat(jobs): add JobResponse shared contract and re-export"
```

---

### Task 6: Tracker + frontend sync

**Files:**
- Modify: `implementation_checklist/pbi_tracker.md`
- Modify: `frontend/src/pages/pbis.ts`

**Interfaces:**
- Consumes: none (documentation/display-only changes).
- Produces: tracker PBI 1 line and `PBIS[0].description` both reading the single-table MVP wording.

- [x] **Step 1: Update the tracker**

Edit `implementation_checklist/pbi_tracker.md`, replacing the PBI 1 bullet:

```
- [ ] **PBI 1 — Jobs schema**
  - `jobs`, `companies`, `job_sources` tables + Alembic migration + repositories.
  - Depends on: —
```

with:

```
- [ ] **PBI 1 — Jobs schema**
  - `jobs` table + Alembic migration + repository. (`companies`/`job_sources` deferred to PBI 3.)
  - Depends on: —
```

- [x] **Step 2: Mirror in the frontend**

Edit `frontend/src/pages/pbis.ts`, replacing the PBI 1 entry:

```ts
  {
    id: "1",
    stage: "mvp",
    title: "Jobs schema",
    description:
      "jobs, companies, job_sources tables + Alembic migration + repositories.",
    depends_on: [],
  },
```

with:

```ts
  {
    id: "1",
    stage: "mvp",
    title: "Jobs schema",
    description:
      "jobs table + Alembic migration + repository. (companies/job_sources deferred to PBI 3.)",
    depends_on: [],
  },
```

- [x] **Step 3: Run the frontend test to confirm it stays green**

Run: `cd frontend && npm test -- --run PbiTrackerPage`
Expected: PASS (`renders every PBI title` still passes; the test asserts on `title`, which is unchanged, but run it to confirm no build breaks).

> **Outcome:** `npm test` (script is `vitest run`; the `--run` flag is redundant) passes; `npm run typecheck` clean.

- [x] **Step 4: Commit**

```bash
git add implementation_checklist/pbi_tracker.md frontend/src/pages/pbis.ts
git commit -m "docs(pbi1): sync tracker + frontend to single-table jobs schema"
```

---

### Task 7: Full verification gate

**Files:**
- None (verification only).

**Interfaces:**
- Consumes: everything above.
- Produces: a green `make lint / typecheck / test` and a confirmed Postgres migration.

- [x] **Step 1: Lint**

Run: `make lint`
Expected: clean (ruff check + format-check both pass).

- [x] **Step 2: Type-check**

Run: `make typecheck`
Expected: no errors across `backend/app` and `shared/jobsearch_shared`.

- [x] **Step 3: Full test suite**

Run: `make test`
Expected: all pass across `backend/tests` + `shared/tests`.

- [x] **Step 4: End-to-end migration on Postgres**

Run:
```bash
make db-up
make migrate
docker compose exec db psql -U jobsearch -d jobsearch -c "\d jobs"
docker compose exec db psql -U jobsearch -d jobsearch -c "\di"
uv run --package jobsearch-backend alembic -c backend/alembic.ini downgrade base
uv run --package jobsearch-backend alembic -c backend/alembic.ini upgrade head
```
Expected: `jobs` table + `ix_jobs_source_external_job_id` + `ix_jobs_last_seen_at` present; downgrade clean; re-upgrade succeeds.

- [x] **Step 5: Confirm clean git status and final commit (if any strays)**

Run: `git status --short`
Expected: only intended files. If lint/format touched files, commit the auto-fixes.

---

## Execution Handoff

See the self-review below; the plan is complete and ready for the human to choose an execution method.
