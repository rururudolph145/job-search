from app.models import Base, Job
from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import Session


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
        job_id = job.id

    with Session(engine) as session:
        stored = session.get(Job, job_id)
        assert stored is not None
        assert stored.company is None
        assert stored.title == "Software Engineer"
