from __future__ import annotations

from datetime import datetime

from sqlalchemy.orm import Session

from app.ingestion.service import IngestionResult
from app.models import CrawlRun


class CrawlRunRepository:
    """Stateless access to ``crawl_runs``; commits belong to the caller (§6.7)."""

    def start(
        self, session: Session, *, source: str, trigger: str, now: datetime
    ) -> CrawlRun:
        run = CrawlRun(
            source=source,
            trigger=trigger,
            status="running",
            started_at=now,
            finished_at=None,
        )
        session.add(run)
        session.flush()
        return run

    def finish(
        self, session: Session, run: CrawlRun, result: IngestionResult, now: datetime
    ) -> None:
        run.status = "succeeded"
        run.finished_at = now
        run.created = result.created
        run.seen = result.seen
        run.skipped_no_id = result.skipped_no_id

    def fail(self, session: Session, run: CrawlRun, error: str, now: datetime) -> None:
        run.status = "failed"
        run.finished_at = now
        run.error = error

    def record_skipped(
        self, session: Session, *, source: str, trigger: str, now: datetime
    ) -> CrawlRun:
        # Written terminal directly, never transiently ``running``: a skipped run
        # did not crawl, so it must not look like one that died mid-flight.
        run = CrawlRun(
            source=source,
            trigger=trigger,
            status="skipped_locked",
            started_at=now,
            finished_at=now,
        )
        session.add(run)
        session.flush()
        return run
