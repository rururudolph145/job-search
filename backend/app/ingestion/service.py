"""IngestionService — the single DB-touching unit in the ingestion layer."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.ingestion.sources.base import JobSource
from app.models import Job
from app.repositories.job import JobRepository


@dataclass(frozen=True)
class IngestionResult:
    created: int
    seen: int
    skipped_no_id: int


class IngestionService:
    def __init__(
        self,
        source: JobSource,
        session_factory: Callable[[], Session],
        now_provider: Callable[[], datetime] | None = None,
    ) -> None:
        self.source = source
        self.session_factory = session_factory
        self.now_provider = now_provider or (lambda: datetime.now(timezone.utc))
        self.repository = JobRepository()

    def run(self) -> IngestionResult:
        session = self.session_factory()
        now = self.now_provider()
        created = 0
        seen = 0
        try:
            for draft in self.source.fetch():
                existing = self.repository.find_by_external_id(
                    session,
                    source=self.source.name,
                    external_job_id=draft.external_job_id,
                )
                if existing is not None:
                    existing.last_seen_at = now
                    seen += 1
                else:
                    job = Job(
                        source=self.source.name,
                        external_job_id=draft.external_job_id,
                        title=draft.title,
                        company=draft.company,
                        location=draft.location,
                        first_seen_at=now,
                        last_seen_at=now,
                    )
                    self.repository.add(session, job)
                    created += 1
            session.commit()
        except BaseException:
            session.rollback()
            raise
        return IngestionResult(
            created=created,
            seen=seen,
            skipped_no_id=self.source.skipped_no_id,
        )
