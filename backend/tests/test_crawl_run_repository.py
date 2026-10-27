from datetime import datetime, timezone

import pytest
from sqlalchemy import Engine, create_engine, select
from sqlalchemy.orm import Session

from app.ingestion.service import IngestionResult
from app.models import Base, CrawlRun
from app.repositories.crawl_run import CrawlRunRepository

FIXED_NOW = datetime(2026, 10, 27, 6, 17, 0, tzinfo=timezone.utc)
FINISHED_NOW = datetime(2026, 10, 27, 6, 19, 0, tzinfo=timezone.utc)


@pytest.fixture()
def engine() -> Engine:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return engine


@pytest.fixture()
def session(engine: Engine) -> Session:
    with Session(engine) as s:
        yield s


def _persisted(engine: Engine) -> list[CrawlRun]:
    # A fresh session reads back what was committed; SQLite stores
    # DateTime(timezone=True) without the offset, so stored values are naive.
    with Session(engine) as s:
        return list(s.scalars(select(CrawlRun)))


def test_start_then_finish_writes_complete_row(engine: Engine) -> None:
    repo = CrawlRunRepository()
    with Session(engine) as session:
        run = repo.start(
            session, source="google_careers", trigger="cron", now=FIXED_NOW
        )
        session.commit()
        assert run.status == "running"
        assert run.started_at == FIXED_NOW.replace(tzinfo=None)
        assert run.finished_at is None

        repo.finish(
            session,
            run,
            IngestionResult(created=3, seen=1, skipped_no_id=0),
            now=FINISHED_NOW,
        )
        session.commit()

    rows = _persisted(engine)
    assert len(rows) == 1
    assert rows[0].status == "succeeded"
    assert rows[0].started_at == FIXED_NOW.replace(tzinfo=None)
    assert rows[0].finished_at == FINISHED_NOW.replace(tzinfo=None)
    assert rows[0].created == 3
    assert rows[0].seen == 1
    assert rows[0].skipped_no_id == 0
    assert rows[0].trigger == "cron"
    assert rows[0].error is None


def test_fail_writes_error_and_counts_stay_null(engine: Engine) -> None:
    repo = CrawlRunRepository()
    with Session(engine) as session:
        run = repo.start(
            session, source="google_careers", trigger="manual", now=FIXED_NOW
        )
        repo.fail(session, run, "FetchError: boom", now=FINISHED_NOW)
        session.commit()

    (row,) = _persisted(engine)
    assert row.status == "failed"
    assert row.error == "FetchError: boom"
    assert row.finished_at == FINISHED_NOW.replace(tzinfo=None)
    assert row.created is None
    assert row.seen is None
    assert row.skipped_no_id is None


def test_record_skipped_is_terminal_not_running(engine: Engine) -> None:
    repo = CrawlRunRepository()
    with Session(engine) as session:
        repo.record_skipped(
            session, source="google_careers", trigger="cron", now=FIXED_NOW
        )
        session.commit()

    (row,) = _persisted(engine)
    assert row.status == "skipped_locked"
    assert row.started_at == FIXED_NOW.replace(tzinfo=None)
    assert row.finished_at == FIXED_NOW.replace(tzinfo=None)
    assert row.created is None
