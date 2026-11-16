from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import datetime, timezone

import app.ingestion.run as run_module
from _pytest.monkeypatch import MonkeyPatch
from app.ingestion.drafts import JobDraft
from app.ingestion.run import IngestRun, RunOutcome
from app.ingestion.sources.base import JobSource
from app.models import Base, CrawlRun, Job
from sqlalchemy import Engine, create_engine, select
from sqlalchemy.orm import Session

FIXED_NOW = datetime(2026, 10, 27, 6, 17, 0, tzinfo=timezone.utc)


class FakeSource:
    """Yields ``drafts`` and records whether ``fetch`` was invoked."""

    name = "google_careers"
    skipped_no_id = 0

    def __init__(self, drafts: list[JobDraft]) -> None:
        self._drafts = drafts
        self.fetched = False

    def fetch(self) -> Iterator[JobDraft]:
        self.fetched = True
        yield from self._drafts


class ExplodingSource:
    name = "google_careers"
    skipped_no_id = 0

    def __init__(self, exc: BaseException) -> None:
        self._exc = exc
        self.fetched = False

    def fetch(self) -> Iterator[JobDraft]:
        self.fetched = True
        raise self._exc
        yield  # pragma: no cover


def _draft(external_job_id: str) -> JobDraft:
    return JobDraft(
        external_job_id=external_job_id,
        title="SWE",
        company=None,
        location="Tokyo",
        url=f"https://careers.google.com/jobs/results/{external_job_id}-sw/",
    )


def _engine() -> Engine:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return engine


def _factory(engine: Engine) -> Callable[[], Session]:
    def make() -> Session:
        return Session(engine)

    return make


def _runs(engine: Engine) -> list[CrawlRun]:
    with Session(engine) as s:
        return list(s.scalars(select(CrawlRun)))


def _jobs(engine: Engine) -> list[Job]:
    with Session(engine) as s:
        return list(s.scalars(select(Job)))


def _run(source: JobSource, engine: Engine, trigger: str = "cron") -> RunOutcome:
    return IngestRun(
        source, _factory(engine), trigger, now_provider=lambda: FIXED_NOW
    ).run()


def test_success_writes_succeeded_row_and_jobs() -> None:
    engine = _engine()
    outcome = _run(FakeSource([_draft("1")]), engine)

    assert outcome == RunOutcome(0, outcome.result, None, skipped_locked=False)
    assert outcome.result is not None
    assert outcome.result.created == 1
    assert outcome.result.seen == 0

    (row,) = _runs(engine)
    assert row.status == "succeeded"
    assert row.trigger == "cron"
    assert row.started_at == FIXED_NOW.replace(tzinfo=None)
    assert row.finished_at == FIXED_NOW.replace(tzinfo=None)
    assert row.created == 1
    assert row.seen == 0
    assert row.skipped_no_id == 0
    assert row.error is None

    assert [j.external_job_id for j in _jobs(engine)] == ["1"]


def test_started_at_and_job_timestamps_share_one_clock() -> None:
    engine = _engine()
    _run(FakeSource([_draft("1")]), engine)
    (row,) = _runs(engine)
    (job,) = _jobs(engine)
    assert row.started_at == job.first_seen_at == job.last_seen_at


def test_failure_rolls_back_jobs_and_marks_failed() -> None:
    engine = _engine()
    outcome = _run(ExplodingSource(RuntimeError("boom")), engine)

    assert outcome.exit_code == 1
    assert outcome.result is None
    assert outcome.error == "RuntimeError: boom"
    assert outcome.skipped_locked is False

    (row,) = _runs(engine)
    assert row.status == "failed"
    assert row.error == "RuntimeError: boom"
    assert row.finished_at == FIXED_NOW.replace(tzinfo=None)
    assert row.created is None
    assert _jobs(engine) == []


def test_lock_held_writes_skipped_row_and_never_fetches(
    monkeypatch: MonkeyPatch,
) -> None:
    @contextmanager
    def denied(_session: Session) -> Iterator[bool]:
        yield False

    monkeypatch.setattr(run_module, "ingestion_lock", denied)
    engine = _engine()
    source = FakeSource([_draft("1")])
    outcome = _run(source, engine)

    assert outcome == RunOutcome(2, None, None, skipped_locked=True)
    assert source.fetched is False

    (row,) = _runs(engine)
    assert row.status == "skipped_locked"
    assert row.started_at == row.finished_at == FIXED_NOW.replace(tzinfo=None)
    assert _jobs(engine) == []


def test_running_row_is_committed_before_the_crawl_starts() -> None:
    # A process killed mid-crawl (no exception handling runs) must leave a
    # `running` row with finished_at NULL — PBI 8 reads that as "unknown", never
    # as a success. Only a commit before the crawl makes that possible.
    engine = _engine()
    seen_during_crawl: list[str] = []

    class PeekingSource:
        name = "google_careers"
        skipped_no_id = 0

        def fetch(self) -> Iterator[JobDraft]:
            seen_during_crawl.extend(r.status for r in _runs(engine))
            yield _draft("1")

    _run(PeekingSource(), engine)

    assert seen_during_crawl == ["running"]


def test_keyboard_interrupt_still_closes_the_run_row() -> None:
    engine = _engine()
    outcome = _run(ExplodingSource(KeyboardInterrupt()), engine)

    assert outcome.exit_code == 1
    assert outcome.error == "KeyboardInterrupt: "
    (row,) = _runs(engine)
    assert row.status == "failed"
    assert row.finished_at is not None
    assert _jobs(engine) == []
