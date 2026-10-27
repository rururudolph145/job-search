from sqlalchemy import create_engine, inspect

from app.models import Base


def test_crawl_runs_table_has_expected_columns() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    insp = inspect(engine)
    assert "crawl_runs" in insp.get_table_names()

    cols = {c["name"]: c for c in insp.get_columns("crawl_runs")}
    assert set(cols) == {
        "id",
        "source",
        "trigger",
        "status",
        "started_at",
        "finished_at",
        "created",
        "seen",
        "skipped_no_id",
        "error",
    }
    assert cols["source"]["nullable"] is False
    assert cols["trigger"]["nullable"] is False
    assert cols["status"]["nullable"] is False
    assert cols["started_at"]["nullable"] is False
    assert cols["finished_at"]["nullable"] is True
    assert cols["created"]["nullable"] is True
    assert cols["seen"]["nullable"] is True
    assert cols["skipped_no_id"]["nullable"] is True
    assert cols["error"]["nullable"] is True


def test_crawl_runs_has_started_at_index() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    insp = inspect(engine)
    index_names = {ix["name"] for ix in insp.get_indexes("crawl_runs")}
    assert "ix_crawl_runs_started_at" in index_names
