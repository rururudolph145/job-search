import pytest
from app.db import engine as engine_mod
from app.models import Base, Job
from app.repositories.job import JobRepository
from sqlalchemy import create_engine, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session


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
    job_id = job.id

    fetched = repo.get(session, job_id)
    assert fetched is not None
    assert fetched.id == job_id
    assert repo.get(session, 999999) is None


def test_find_by_external_id_returns_none_when_absent(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(engine_mod, "engine", session.get_bind())
    repo = JobRepository()
    assert (
        repo.find_by_external_id(
            session, source="google_careers", external_job_id="nope"
        )
        is None
    )


def test_find_by_external_id_returns_match(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(engine_mod, "engine", session.get_bind())
    repo = JobRepository()
    job = _make_job()
    session.add(job)
    session.commit()
    job_id = job.id

    found = repo.find_by_external_id(
        session, source="google_careers", external_job_id="123"
    )
    assert found is not None
    assert found.id == job_id


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


def test_duplicate_source_external_id_raises(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(engine_mod, "engine", session.get_bind())
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
