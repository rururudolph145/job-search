"""IngestionService — the single DB-touching unit in the ingestion layer."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.ingestion.drafts import JobDraft
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

    def run(self, session: Session | None = None) -> IngestionResult:
        """Ingest the source's drafts.

        With ``session=None`` a session is opened from ``session_factory``, used,
        and closed here. A caller-supplied ``session`` (``IngestRun``) is used and
        committed on, but **not** closed: the caller owns its lifetime and the
        surrounding transaction (§6.7).
        """
        owned = session is None
        if session is None:
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
                    self._apply_sighting(existing, draft, now)
                    seen += 1
                else:
                    job = Job(
                        source=self.source.name,
                        external_job_id=draft.external_job_id,
                        title=draft.title,
                        company=draft.company,
                        location=draft.location,
                        city=draft.city,
                        country=draft.country,
                        first_seen_at=now,
                        last_seen_at=now,
                    )
                    try:
                        self.repository.add(session, job)
                        created += 1
                    except IntegrityError:
                        # A concurrent writer (or an in-run duplicate already
                        # flushed) beat us to this identity. Roll back the
                        # poisoned insert, re-read, and count it as `seen`.
                        # This requires the flush in `add` (which it has) so the
                        # constraint is evaluated per-draft, not at commit.
                        session.rollback()
                        existing = self.repository.find_by_external_id(
                            session,
                            source=self.source.name,
                            external_job_id=draft.external_job_id,
                        )
                        if existing is not None:
                            self._apply_sighting(existing, draft, now)
                            seen += 1
                        else:
                            # Re-insert failed to find a row we can bump; surface
                            # rather than silently drop the draft.
                            raise
            session.commit()
        except BaseException:
            session.rollback()
            raise
        finally:
            if owned:
                session.close()
        return IngestionResult(
            created=created,
            seen=seen,
            skipped_no_id=self.source.skipped_no_id,
        )

    @staticmethod
    def _apply_sighting(job: Job, draft: JobDraft, now: datetime) -> None:
        """Bump a re-sighted job and backfill location fields from the draft."""
        job.last_seen_at = now
        job.city = draft.city
        job.country = draft.country
