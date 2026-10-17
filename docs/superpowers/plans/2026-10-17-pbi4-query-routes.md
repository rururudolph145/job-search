# PBI 4 — Query Routes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Expose list/filter and detail endpoints for the ingested `jobs` table.

**Architecture:** Three read-only HTTP handlers (`GET /jobs` list-with-envelope, `GET /jobs/{job_id}` detail) backed by the existing `JobRepository`, whose `list()` gains filter args and which gains a new `count()`. One new shared contract (`JobListResponse`). No schema change, no write path.

**Tech Stack:** FastAPI (dependency injection, `Query` validation, `HTTPException`), SQLAlchemy 2.0 ORM (`Select`, `func`, `ilike`), Pydantic v2 (`ConfigDict(from_attributes=True)`), pytest + `TestClient` + in-memory SQLite.

**Spec:** `docs/superpowers/specs/2026-10-17-pbi4-query-routes-design.md`

## Global Constraints

- Ruff enforces double quotes and ignores E501 (88-char line length).
- Mypy runs in strict mode (`disallow_untyped_defs`, `no_implicit_optional`).
- Unit tests use in-memory SQLite; Postgres is only exercised via Docker Compose. No `conftest.py`; each test module is standalone.
- Filterable fields are limited to existing `jobs` columns: `source`, `company`, `location` (exact) + `q` (title `ilike`). No new columns.
- `limit` bounded `ge=1 le=100` (default 50); `offset` `ge=0` (default 0).

## Review Focus

These are the input classes and failure modes the spec implies but no happy-path test will exercise naturally. Each is pinned by a test in its owning task.

1. **`q` matching is case-insensitive and substring, not equality** — a person typing `software` expects to match `Senior Software Engineer` regardless of case. Pinned in Task 3 (`test_list_q_case_insensitive_substring`).
2. **Empty result set must return a well-formed envelope** — no jobs matching a filter should return `{ items: [], total: 0 }`, not `{}` or `null`. Pinned in Task 4 (`test_list_empty_returns_zero_envelope`).
3. **`total` must count the filtered set, not the whole table** — a filtered `q` result must report the matching `total`, or pagination lies. Pinned in Task 4 (`test_list_total_reflects_filters`).
4. **Out-of-range `limit` is rejected cleanly, not passed to SQL** — `limit=0` or `limit=101` must yield `422`, not a SQL error or a crash. Pinned in Task 4 (`test_list_limit_bounds`).
5. **Unknown `job_id` returns `404` with a body, not `200`/`null`** — a stale bookmark must be distinguishable from an empty detail. Pinned in Task 5 (`test_get_job_not_found`).

---

### Task 1: Add `JobListResponse` contract

**Files:**
- Modify: `shared/jobsearch_shared/schemas.py` (append after `JobResponse`)
- Modify: `backend/app/schemas/__init__.py` (re-export)
- Test: `shared/tests/test_job_response.py`

**Interfaces:**
- Consumes: `JobResponse` (already in `shared/jobsearch_shared/schemas.py`).
- Produces: `JobListResponse` with fields `items: list[JobResponse]`, `total: int`; re-exported from `app.schemas`.

- [x] **Step 1: Write the failing test**

Append to `shared/tests/test_job_response.py`:

```python
from jobsearch_shared.schemas import JobListResponse, JobResponse


def test_job_list_response_roundtrip() -> None:
    now = datetime(2026, 10, 17, 12, 0, 0, tzinfo=timezone.utc)
    item = JobResponse(
        id=1,
        source="google_careers",
        external_job_id="123",
        title="Software Engineer",
        company=None,
        location="Tokyo",
        first_seen_at=now,
        last_seen_at=now,
        updated_at=now,
    )
    resp = JobListResponse(items=[item], total=1)
    assert resp.total == 1
    assert resp.items[0].id == 1
    assert resp.model_dump() == {
        "items": [
            {
                "id": 1,
                "source": "google_careers",
                "external_job_id": "123",
                "title": "Software Engineer",
                "company": None,
                "location": "Tokyo",
                "first_seen_at": now,
                "last_seen_at": now,
                "updated_at": now,
            }
        ],
        "total": 1,
    }
```

(Update the import at the top of the file from
`from jobsearch_shared.schemas import JobResponse` to import both names.)

- [x] **Step 2: Run test to verify it fails**

Run: `uv run --package jobsearch-shared pytest shared/tests/test_job_response.py -v` (from repo root)
Expected: FAIL with `ImportError: cannot import name 'JobListResponse'`.

- [x] **Step 3: Write minimal implementation**

Append to `shared/jobsearch_shared/schemas.py`:

```python
class JobListResponse(BaseModel):
    items: list[JobResponse]
    total: int
```

- [x] **Step 4: Modify re-export**

In `backend/app/schemas/__init__.py`, change the import and `__all__` to include `JobListResponse`:

```python
from jobsearch_shared.schemas import HealthResponse, JobListResponse, JobResponse

__all__ = ["HealthResponse", "JobListResponse", "JobResponse"]
```

- [x] **Step 5: Run test to verify it passes**

Run: `uv run --package jobsearch-shared pytest shared/tests/test_job_response.py -v`
Expected: PASS (4 tests).

- [x] **Step 6: Commit**

```bash
git add shared/jobsearch_shared/schemas.py backend/app/schemas/__init__.py shared/tests/test_job_response.py
git commit -m "feat(jobs): add JobListResponse list contract"
```

---

### Task 2: Add `_apply_filters` + `count()` to repository; extend `list()`

**Files:**
- Modify: `backend/app/repositories/job.py`
- Test: `backend/tests/test_job_repository.py`

**Interfaces:**
- Consumes: `Job` model (from `app.models`), `select`/`func` from SQLAlchemy.
- Produces:
  - `JobRepository._apply_filters(stmt: Select, *, source: str | None, company: str | None, location: str | None, q: str | None) -> Select`
  - `JobRepository.list(session, *, limit: int, offset: int, source: str | None = None, company: str | None = None, location: str | None = None, q: str | None = None) -> list[Job]`
  - `JobRepository.count(session, *, source: str | None = None, company: str | None = None, location: str | None = None, q: str | None = None) -> int`

- [x] **Step 1: Write the failing tests**

Append to `backend/tests/test_job_repository.py`. The existing module already imports `Session`, `Base`, `Job`, `JobRepository`, `create_engine`, `select`, and has the `session` fixture and `_make_job` helper. Add these tests (they reuse `_make_job` and `session`/`monkeypatch` unchanged):

```python
def test_list_filters_by_source(session: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(engine_mod, "engine", session.get_bind())
    repo = JobRepository()
    session.add(_make_job(source="google_careers", title="A"))
    session.add(_make_job(source="linkedin", title="B"))
    session.commit()

    rows = repo.list(session, limit=10, offset=0, source="linkedin")
    assert [r.title for r in rows] == ["B"]


def test_list_filters_by_q_case_insensitive(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(engine_mod, "engine", session.get_bind())
    repo = JobRepository()
    session.add(_make_job(title="Senior Software Engineer"))
    session.add(_make_job(title="Data Analyst"))
    session.commit()

    rows = repo.list(session, limit=10, offset=0, q="SOFTWARE")
    assert [r.title for r in rows] == ["Senior Software Engineer"]


def test_list_filters_by_company_and_location(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(engine_mod, "engine", session.get_bind())
    repo = JobRepository()
    session.add(_make_job(company="Google", location="Tokyo", title="A"))
    session.add(_make_job(company="Meta", location="Tokyo", title="B"))
    session.add(_make_job(company="Google", location="Osaka", title="C"))
    session.commit()

    rows = repo.list(
        session, limit=10, offset=0, company="Google", location="Tokyo"
    )
    assert [r.title for r in rows] == ["A"]


def test_count_with_and_without_filters(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(engine_mod, "engine", session.get_bind())
    repo = JobRepository()
    session.add(_make_job(source="google_careers", title="Software Engineer"))
    session.add(_make_job(source="google_careers", title="Data Analyst"))
    session.add(_make_job(source="linkedin", title="Software Engineer"))
    session.commit()

    assert repo.count(session) == 3
    assert repo.count(session, q="software") == 2
    assert repo.count(session, source="linkedin") == 1
    assert repo.count(session, source="linkedin", q="data") == 0
```

- [x] **Step 2: Run tests to verify they fail**

Run: `uv run --package jobsearch-backend pytest backend/tests/test_job_repository.py -v` (from repo root)
Expected: FAIL — `list()` takes keyword args but `source`/`company`/`location`/`q` are unexpected; `count` is undefined.

- [x] **Step 3: Write minimal implementation**

Replace the top of `backend/app/repositories/job.py` — its `import` block and the `get`/`list` methods — with:

```python
from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

from app.models import Job


class JobRepository:
    def get(self, session: Session, job_id: int) -> Job | None:
        return session.get(Job, job_id)

    @staticmethod
    def _apply_filters(
        stmt: Select,
        *,
        source: str | None,
        company: str | None,
        location: str | None,
        q: str | None,
    ) -> Select:
        if source is not None:
            stmt = stmt.where(Job.source == source)
        if company is not None:
            stmt = stmt.where(Job.company == company)
        if location is not None:
            stmt = stmt.where(Job.location == location)
        if q is not None:
            stmt = stmt.where(Job.title.ilike(f"%{q}%"))
        return stmt

    def list(
        self,
        session: Session,
        *,
        limit: int,
        offset: int,
        source: str | None = None,
        company: str | None = None,
        location: str | None = None,
        q: str | None = None,
    ) -> list[Job]:
        stmt = self._apply_filters(
            select(Job), source=source, company=company, location=location, q=q
        ).order_by(Job.id)
        stmt = stmt.limit(limit).offset(offset)
        return list(session.scalars(stmt))

    def count(
        self,
        session: Session,
        *,
        source: str | None = None,
        company: str | None = None,
        location: str | None = None,
        q: str | None = None,
    ) -> int:
        stmt = self._apply_filters(
            select(func.count()).select_from(Job),
            source=source,
            company=company,
            location=location,
            q=q,
        )
        return session.scalar(stmt) or 0
```

Keep the existing `add` and `find_by_external_id` methods below `count` unchanged.

- [x] **Step 4: Run tests to verify they pass**

Run: `uv run --package jobsearch-backend pytest backend/tests/test_job_repository.py -v` (from repo root)
Expected: PASS (existing 8 + new 4 = 12 tests).

- [x] **Step 5: Commit**

```bash
git add backend/app/repositories/job.py backend/tests/test_job_repository.py
git commit -m "feat(jobs): add filter args to list + count to JobRepository"
```

---

### Task 3: Add `GET /jobs` list endpoint

**Files:**
- Create: `backend/app/api/routes/jobs.py`
- Modify: `backend/app/main.py` (import + include router)
- Test: `backend/tests/test_routes_jobs.py`

**Interfaces:**
- Consumes: `JobRepository.list`/`count` (Task 2), `JobListResponse`/`JobResponse` (Task 1), `get_session` from `app.db.engine`.
- Produces: `router` (FastAPI `APIRouter` with `prefix="/jobs"`), registered in `app.main`.

- [x] **Step 1: Write the failing test**

Create `backend/tests/test_routes_jobs.py`:

```python
from collections.abc import Iterator

import pytest
from app.db import engine as engine_mod
from app.main import app
from app.models import Base, Job
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session


@pytest.fixture()
def client(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    test_engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(test_engine)
    with Session(test_engine) as session:
        session.add(
            Job(
                source="google_careers",
                external_job_id="123",
                title="Software Engineer",
                company="Google",
                location="Tokyo",
            )
        )
        session.add(
            Job(
                source="linkedin",
                external_job_id="456",
                title="Data Analyst",
                company=None,
                location=None,
            )
        )
        session.commit()
    monkeypatch.setattr(engine_mod, "engine", test_engine)
    yield TestClient(app)


def test_list_jobs_returns_envelope(client: TestClient) -> None:
    resp = client.get("/jobs")
    assert resp.status_code == 200
    body = resp.json()
    assert set(body.keys()) == {"items", "total"}
    assert body["total"] == 2
    assert [item["title"] for item in body["items"]] == [
        "Software Engineer",
        "Data Analyst",
    ]


def test_list_jobs_source_filter(client: TestClient) -> None:
    resp = client.get("/jobs", params={"source": "linkedin"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 1
    assert [item["title"] for item in body["items"]] == ["Data Analyst"]


def test_list_jobs_q_case_insensitive_substring(client: TestClient) -> None:
    resp = client.get("/jobs", params={"q": "SOFTWARE"})
    body = resp.json()
    assert [item["title"] for item in body["items"]] == ["Software Engineer"]
```

- [x] **Step 2: Run tests to verify they fail**

Run: `uv run --package jobsearch-backend pytest backend/tests/test_routes_jobs.py -v` (from repo root)
Expected: FAIL — `GET /jobs` returns `404` (no route yet).

- [x] **Step 3: Write minimal implementation**

Create `backend/app/api/routes/jobs.py` (implemented with `Depends(get_db)`
rather than `Depends(get_session)` — see the note at the end of this task):

```python
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.db.engine import get_session
from app.repositories.job import JobRepository
from app.schemas import JobListResponse

router = APIRouter(prefix="/jobs", tags=["jobs"])


def _get_repo() -> JobRepository:
    return JobRepository()


@router.get("", response_model=JobListResponse)
async def list_jobs(
    session: Annotated[Session, Depends(get_session)],
    repo: Annotated[JobRepository, Depends(_get_repo)],
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
    source: Annotated[str | None, Query()] = None,
    company: Annotated[str | None, Query()] = None,
    location: Annotated[str | None, Query()] = None,
    q: Annotated[str | None, Query()] = None,
) -> JobListResponse:
    jobs = repo.list(
        session,
        limit=limit,
        offset=offset,
        source=source,
        company=company,
        location=location,
        q=q,
    )
    total = repo.count(
        session, source=source, company=company, location=location, q=q
    )
    return JobListResponse(items=jobs, total=total)
```

- [x] **Step 4: Register the router**

In `backend/app/main.py`, change the import line to:

```python
from app.api.routes import health, jobs
```

and add, after `app.include_router(health.router)`:

```python
app.include_router(jobs.router)
```

- [x] **Step 5: Run tests to verify they pass**

Run: `uv run --package jobsearch-backend pytest backend/tests/test_routes_jobs.py -v` (from repo root)
Expected: PASS (3 tests).

- [x] **Step 6: Commit**

```bash
git add backend/app/api/routes/jobs.py backend/app/main.py backend/tests/test_routes_jobs.py
git commit -m "feat(jobs): add GET /jobs list endpoint with filters + envelope"
```

---

---

**Implementation deviations (recorded 2026-10-17):**

- `get_session` in `app/db/engine.py` is a `@contextmanager`. Handing it to
  `Depends` makes FastAPI wrap it a second time, so *every* request failed with
  `TypeError: '_GeneratorContextManager' object is not an iterator`. Added
  `get_db` (plain generator, same `engine`/pool) in a separate commit,
  `fix(db): add get_db generator for FastAPI Depends`, pinned by
  `test_engine.py::test_get_db_works_as_fastapi_dependency` (asserts the session
  is closed when the request ends; mutation-checked).
- The in-memory SQLite fixture needs
  `connect_args={"check_same_thread": False}, poolclass=StaticPool` because the
  dependency runs in FastAPI's worker thread.
- mypy strict rejects `list[Job]` for `items: list[JobResponse]`, so the handler
  builds `[JobResponse.model_validate(job) for job in jobs]` (the pattern used
  by `load_app_config`).

### Task 4: Harden list endpoint (empty set, total-vs-filters, bounds)

**Files:**
- Test: `backend/tests/test_routes_jobs.py`

**Interfaces:**
- Consumes: `list_jobs` endpoint (Task 3).

- [x] **Step 1: Write the failing tests**

Append to `backend/tests/test_routes_jobs.py`:

```python
def test_list_empty_returns_zero_envelope(client: TestClient) -> None:
    resp = client.get("/jobs", params={"source": "nonexistent"})
    assert resp.status_code == 200
    assert resp.json() == {"items": [], "total": 0}


def test_list_total_reflects_filters(client: TestClient) -> None:
    # q="software" matches 1 row, but total must be 1 (not the 2-row table total).
    resp = client.get("/jobs", params={"q": "software"})
    body = resp.json()
    assert body["total"] == 1
    assert len(body["items"]) == 1


def test_list_limit_bounds(client: TestClient) -> None:
    assert client.get("/jobs", params={"limit": "0"}).status_code == 422
    assert client.get("/jobs", params={"limit": "101"}).status_code == 422
    assert client.get("/jobs", params={"offset": "-1"}).status_code == 422
```

- [x] **Step 2: Run tests to verify they fail**

Run: `uv run --package jobsearch-backend pytest backend/tests/test_routes_jobs.py -v` (from repo root)
Expected: PASS on `test_list_empty_returns_zero_envelope` and `test_list_total_reflects_filters` (already correct count is `or 0`; filters already applied to count), but FAIL on `test_list_limit_bounds` if the `Query(ge=1, le=100)` constraints are not yet present. If the endpoint was already written with those constraints in Task 3, all three pass — in that case this task's "fail" gate is already satisfied and you proceed to commit. The point of this task is that these three inputs are *pinned by explicit tests*; do not skip them.

- [x] **Step 3: Implement only what is missing**

If `test_list_limit_bounds` failed, the `Query(ge=1, le=100)` / `Query(ge=0)` bounds on `list_jobs` (Task 3) are missing — add/ensure them. Otherwise no code change is needed.

- [x] **Step 4: Run tests to verify they pass**

Run: `uv run --package jobsearch-backend pytest backend/tests/test_routes_jobs.py -v` (from repo root)
Expected: PASS (6 tests).

- [x] **Step 5: Commit**

```bash
git add backend/tests/test_routes_jobs.py
git commit -m "test(jobs): pin empty-list, total-filter, and limit-bound behavior"
```

---

**Implemented 2026-10-17:** all 3 tests passed against the Task 3 code immediately (the plan anticipated this). Discriminating power verified by mutation: dropping the count filters fails `test_list_total_reflects_filters` + `test_list_empty_returns_zero_envelope`; removing `le=100` fails `test_list_limit_bounds`; returning `{}` for an empty list fails `test_list_empty_returns_zero_envelope`; making `q` exact fails `test_list_jobs_q_case_insensitive_substring`.

---

### Task 5: Add `GET /jobs/{job_id}` detail endpoint

**Files:**
- Modify: `backend/app/api/routes/jobs.py`
- Test: `backend/tests/test_routes_jobs.py`

**Interfaces:**
- Consumes: `JobRepository.get` (exists since PBI 1), `JobResponse` (Task 1).
- Produces: `get_job(job_id, ...)` handler on the same router.

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_routes_jobs.py`:

```python
def test_get_job_returns_row(client: TestClient) -> None:
    # First find an existing id via the list endpoint.
    listings = client.get("/jobs").json()
    some_id = listings["items"][0]["id"]

    resp = client.get(f"/jobs/{some_id}")
    assert resp.status_code == 200
    assert resp.json()["id"] == some_id


def test_get_job_not_found(client: TestClient) -> None:
    resp = client.get("/jobs/999999999")
    assert resp.status_code == 404
    assert resp.json() == {"detail": "Job not found"}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run --package jobsearch-backend pytest backend/tests/test_routes_jobs.py -v` (from repo root)
Expected: FAIL — `GET /jobs/{job_id}` returns `404` (or `405`) with no `get_job` handler defined.

- [ ] **Step 3: Write minimal implementation**

In `backend/app/api/routes/jobs.py`, make two edits:

**Edit A — imports.** Change

```python
from fastapi import APIRouter, Depends, Query
```

to

```python
from fastapi import APIRouter, Depends, HTTPException, Query
```

and change

```python
from app.schemas import JobListResponse
```

to

```python
from app.schemas import JobListResponse, JobResponse
```

**Edit B — handler.** Add below `list_jobs` (the existing `router = APIRouter(...)` and `_get_repo` remain above, unchanged):

```python
@router.get("/{job_id}", response_model=JobResponse)
async def get_job(
    job_id: int,
    session: Annotated[Session, Depends(get_session)],
    repo: Annotated[JobRepository, Depends(_get_repo)],
) -> JobResponse:
    job = repo.get(session, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return job
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run --package jobsearch-backend pytest backend/tests/test_routes_jobs.py -v` (from repo root)
Expected: PASS (8 tests).

- [ ] **Step 5: Commit**

```bash
git add backend/app/api/routes/jobs.py backend/tests/test_routes_jobs.py
git commit -m "feat(jobs): add GET /jobs/{job_id} detail endpoint"
```

---

### Task 6: Full verification, lint, typecheck, dry-run

**Files:**
- Modify: `implementation_checklist/pbi_tracker.md` (tick PBI 4)

**Interfaces:**
- Consumes: all prior tasks.

- [ ] **Step 1: Run the full test suite**

Run (from repo root):
```bash
make test
```
Expected: all `backend/tests` and `shared/tests` pass.

- [ ] **Step 2: Lint**

Run: `make lint`
Expected: clean.

- [ ] **Step 3: Typecheck**

Run: `make typecheck`
Expected: clean under mypy strict.

- [ ] **Step 4: Tick PBI 4 in the tracker**

In `implementation_checklist/pbi_tracker.md`, change:

```markdown
- [ ] **PBI 4 — Query routes**
```

to:

```markdown
- [x] **PBI 4 — Query routes**
```

Also reconcile PBI 1's checkbox (still `[x]` from PBI 1's own work — leave as-is; the "carried forward" note in the PBI 3 spec §10 documents that PBI 1's line remained unticked at one point, but the tracker now shows PBI 1–3 `[x]`).

- [ ] **Step 5: Commit**

```bash
git add implementation_checklist/pbi_tracker.md
git commit -m "docs(pbi4): tick PBI 4 query routes complete"
```

---

### Task 7: Manual smoke (optional, real Postgres)

**Files:**
- None.

**Interfaces:**
- Consumes: all prior tasks.

- [ ] **Step 1: Start the stack**

Run: `make db-up && make migrate && make dev`
Expected: server at `http://localhost:8000`.

- [ ] **Step 2: Smoke the list endpoint**

Run: `curl -s 'http://localhost:8000/jobs?limit=5'`
Expected: `200` JSON with `items` + `total`.

- [ ] **Step 3: Smoke filters + detail**

Run:
```bash
curl -s 'http://localhost:8000/jobs?source=google_careers&q=software'
curl -s 'http://localhost:8000/jobs/1'
curl -s -o /dev/null -w '%{http_code}' 'http://localhost:8000/jobs/999999999'
```
Expected: filtered list, a job body, then `404`.

- [ ] **Step 4: Tear down**

Run: `make db-down`
Expected: containers stopped.
