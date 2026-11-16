from collections.abc import Callable, Iterator
from datetime import datetime, timezone

import pytest
from app.ingestion.drafts import JobDraft
from app.ingestion.service import IngestionService
from app.models import Base, Job
from sqlalchemy import create_engine, event, select, text
from sqlalchemy.orm import Session


class FakeSource:
    name = "test_source"
    skipped_no_id = 0

    def __init__(self, drafts: list[JobDraft], skipped_no_id: int = 0) -> None:
        self._drafts = drafts
        self.skipped_no_id = skipped_no_id

    def fetch(self) -> Iterator[JobDraft]:
        yield from self._drafts


@pytest.fixture()
def session_factory() -> Callable[[], Session]:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    def factory() -> Session:
        return Session(engine)

    return factory


FIXED_NOW = datetime(2026, 10, 14, 12, 0, 0, tzinfo=timezone.utc)


def _draft(external_job_id: str, title: str = "SWE") -> JobDraft:
    return JobDraft(
        external_job_id=external_job_id,
        title=title,
        company=None,
        location="Tokyo",
        url=f"https://careers.google.com/jobs/results/{external_job_id}-software-engineer/",
    )


def test_new_draft_creates_row(session_factory: Callable[[], Session]) -> None:
    service = IngestionService(
        FakeSource([_draft("123")]),
        session_factory,
        now_provider=lambda: FIXED_NOW,
    )
    result = service.run()
    assert result.created == 1
    assert result.seen == 0
    assert result.skipped_no_id == 0

    with session_factory() as s:
        job = s.scalar(select(Job))
        assert job is not None
        assert job.source == "test_source"
        assert job.external_job_id == "123"
        # SQLite stores DateTime(timezone=True) without the offset, so compare
        # against the naive form; the invariant that first_seen_at == last_seen_at ==
        # the single `now` captured at run start still holds.
        assert job.first_seen_at == FIXED_NOW.replace(tzinfo=None)
        assert job.last_seen_at == FIXED_NOW.replace(tzinfo=None)


def test_duplicate_in_one_run_is_seen(session_factory: Callable[[], Session]) -> None:
    service = IngestionService(
        FakeSource([_draft("123"), _draft("123")]),
        session_factory,
        now_provider=lambda: FIXED_NOW,
    )
    result = service.run()
    assert result.created == 1
    assert result.seen == 1

    with session_factory() as s:
        rows = list(s.scalars(select(Job)))
        assert len(rows) == 1


def test_duplicate_across_runs_bumps_last_seen(
    session_factory: Callable[[], Session],
) -> None:
    first = IngestionService(
        FakeSource([_draft("123")]), session_factory, now_provider=lambda: FIXED_NOW
    )
    assert first.run().created == 1

    later = datetime(2026, 10, 14, 13, 0, 0, tzinfo=timezone.utc)
    second = IngestionService(
        FakeSource([_draft("123")]), session_factory, now_provider=lambda: later
    )
    result = second.run()
    assert result.created == 0
    assert result.seen == 1

    with session_factory() as s:
        rows = list(s.scalars(select(Job)))
        assert len(rows) == 1
        assert rows[0].last_seen_at == later.replace(tzinfo=None)
        assert rows[0].first_seen_at == FIXED_NOW.replace(tzinfo=None)


def test_skipped_no_id_is_reported_without_writing(
    session_factory: Callable[[], Session],
) -> None:
    service = IngestionService(
        FakeSource([], skipped_no_id=1),
        session_factory,
        now_provider=lambda: FIXED_NOW,
    )
    result = service.run()
    assert result.skipped_no_id == 1
    assert result.created == 0

    with session_factory() as s:
        assert s.scalar(select(Job)) is None


def test_empty_source_zero_counts(session_factory: Callable[[], Session]) -> None:
    service = IngestionService(
        FakeSource([]), session_factory, now_provider=lambda: FIXED_NOW
    )
    result = service.run()
    assert result.created == 0
    assert result.seen == 0
    assert result.skipped_no_id == 0


def test_source_error_propagates(session_factory: Callable[[], Session]) -> None:
    class ExplodingSource:
        name = "boom"
        skipped_no_id = 0

        def fetch(self) -> Iterator[JobDraft]:
            raise RuntimeError("sitemap unreachable")
            yield  # pragma: no cover

    service = IngestionService(
        ExplodingSource(), session_factory, now_provider=lambda: FIXED_NOW
    )
    with pytest.raises(RuntimeError):
        service.run()


def _race_session_factory(
    raise_on_insert_id: str,
    winner: dict[str, object] | None = None,
) -> Callable[[], Session]:
    """Session factory whose write path loses a race for ``raise_on_insert_id``.

    The engine is SQLite ``:memory:``, so every session shares one connection.
    When the loser's ORM ``INSERT`` for ``raise_on_insert_id`` executes (at
    ``flush``), the winning row is committed from a side connection and the
    insert is rejected by the unique index — exactly the concurrent-writer
    outcome the service must absorb. ``winner`` supplies extra columns for the
    winning row (e.g. null ``city``/``country`` to prove the re-read backfills).
    """
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    armed = True

    @event.listens_for(engine, "before_cursor_execute")
    def _competitor(
        conn: object,
        cursor: object,
        statement: str,
        parameters: object,
        context: object,
        executemany: bool,
    ) -> None:
        nonlocal armed
        if not armed or not statement.startswith("INSERT INTO jobs "):
            return
        if raise_on_insert_id not in (parameters or ()):
            return
        armed = False  # the winner's own insert must not re-trigger this hook
        with engine.connect() as conn:
            conn.execute(
                Job.__table__.insert().values(
                    source="test_source",
                    external_job_id=raise_on_insert_id,
                    title="Winner",
                    **(winner or {}),
                )
            )
            conn.commit()

    def factory() -> Session:
        return Session(engine)

    return factory


def test_run_with_shared_session_commits_without_closing(
    session_factory: Callable[[], Session],
) -> None:
    service = IngestionService(
        FakeSource([_draft("777")]), session_factory, now_provider=lambda: FIXED_NOW
    )
    with session_factory() as shared:
        result = service.run(session=shared)
        # run() committed on `shared`; a fresh session sees the row.
        assert result.created == 1

    with session_factory() as check:
        job = check.scalar(select(Job).where(Job.external_job_id == "777"))
        assert job is not None


def test_run_with_shared_session_leaves_it_open(
    session_factory: Callable[[], Session],
) -> None:
    # IngestRun owns the transaction and the run row commits after the service
    # returns, so the shared session must still be usable.
    service = IngestionService(
        FakeSource([_draft("888")]), session_factory, now_provider=lambda: FIXED_NOW
    )
    with session_factory() as shared:
        service.run(session=shared)
        assert shared.execute(text("SELECT 1")).scalar() == 1


def test_lost_insert_race_counts_seen_not_crash() -> None:
    service = IngestionService(
        FakeSource([_draft("123")]),
        _race_session_factory("123"),
        now_provider=lambda: FIXED_NOW,
    )

    result = service.run()

    assert result.created == 0
    assert result.seen == 1


def test_lost_insert_race_backfills_country_and_city() -> None:
    # The race-lost re-read path must backfill location too (Review Focus #5),
    # not only bump last_seen_at like a bare re-sight.
    winner = {"city": None, "country": None}
    factory = _race_session_factory("123", winner=winner)
    draft = JobDraft(
        external_job_id="123",
        title="SWE",
        company=None,
        location="Tokyo, Japan",
        url="https://x/123-swe/",
        city="Tokyo",
        country="JP",
    )
    service = IngestionService(
        FakeSource([draft]), factory, now_provider=lambda: FIXED_NOW
    )

    result = service.run()

    assert result.created == 0
    assert result.seen == 1
    with factory() as s:
        job = s.scalar(select(Job).where(Job.external_job_id == "123"))
        assert job.city == "Tokyo"
        assert job.country == "JP"


def test_new_draft_stores_country_and_city(session_factory) -> None:
    draft = JobDraft(
        external_job_id="123",
        title="SWE",
        company=None,
        location="Tokyo, Japan",
        url="https://x/123-swe/",
        city="Tokyo",
        country="JP",
    )
    service = IngestionService(
        FakeSource([draft]), session_factory, now_provider=lambda: FIXED_NOW
    )
    service.run()
    with session_factory() as s:
        job = s.scalar(select(Job))
        assert job.city == "Tokyo"
        assert job.country == "JP"


def test_recrawl_backfills_country_and_city_on_existing_row(session_factory) -> None:
    # Pre-existing row with null city/country (simulates pre-migration data).
    with session_factory() as s:
        s.add(
            Job(
                source="test_source",
                external_job_id="123",
                title="SWE",
                company=None,
                location="Tokyo",
                city=None,
                country=None,
            )
        )
        s.commit()
    draft = JobDraft(
        external_job_id="123",
        title="SWE",
        company=None,
        location="Tokyo, Japan",
        url="https://x/123-swe/",
        city="Tokyo",
        country="JP",
    )
    service = IngestionService(
        FakeSource([draft]), session_factory, now_provider=lambda: FIXED_NOW
    )
    result = service.run()
    assert result.seen == 1
    with session_factory() as s:
        job = s.scalar(select(Job))
        assert job.city == "Tokyo"
        assert job.country == "JP"
