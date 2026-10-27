"""IngestRun — one crawl attempt: advisory lock, run record, then the crawl (§6.7)."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.ingestion.locking import ingestion_lock
from app.ingestion.service import IngestionResult, IngestionService
from app.ingestion.sources.base import JobSource
from app.repositories.crawl_run import CrawlRunRepository


@dataclass(frozen=True, slots=True)
class RunOutcome:
    exit_code: int  # 0 success, 1 crawl failed, 2 skipped (lock held)
    result: IngestionResult | None  # None when skipped or failed
    error: str | None  # set when exit_code == 1
    skipped_locked: bool  # True when exit_code == 2


@dataclass(frozen=True)
class IngestRun:
    source: JobSource
    session_factory: Callable[[], Session]
    trigger: str  # "cron" | "manual"
    now_provider: Callable[[], datetime] | None = None

    def _now(self) -> datetime:
        if self.now_provider is None:
            return datetime.now(timezone.utc)
        return self.now_provider()

    def run(self) -> RunOutcome:
        crawl_runs = CrawlRunRepository()
        session = self.session_factory()
        # One clock source: the same `now` stamps the run row and the jobs.
        now = self._now()
        try:
            with ingestion_lock(session) as held:
                if not held:
                    crawl_runs.record_skipped(
                        session, source=self.source.name, trigger=self.trigger, now=now
                    )
                    session.commit()
                    return RunOutcome(2, None, None, skipped_locked=True)
                run = crawl_runs.start(
                    session, source=self.source.name, trigger=self.trigger, now=now
                )
                # Commit *before* the crawl: a failed crawl calls session.rollback()
                # to discard partial job writes, which would also discard a merely
                # pending `running` row. Surviving in the DB, the row is marked
                # `failed` after the rollback; a process that dies here leaves it
                # `running` with `finished_at IS NULL` — the intended signal (§6.5).
                session.commit()
                try:
                    result = IngestionService(
                        self.source, lambda: session, now_provider=lambda: now
                    ).run(session=session)
                except BaseException as exc:  # noqa: BLE001 — re-raised as outcome
                    # Discard any partial crawl writes, then record the failure on
                    # a clean transaction: a failed run writes no job rows.
                    session.rollback()
                    error = f"{type(exc).__name__}: {exc}"
                    crawl_runs.fail(session, run, error, now)
                    session.commit()
                    return RunOutcome(1, None, error, skipped_locked=False)
                crawl_runs.finish(session, run, result, now)
                session.commit()
                return RunOutcome(0, result, None, skipped_locked=False)
        finally:
            session.close()
