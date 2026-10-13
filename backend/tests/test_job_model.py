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
