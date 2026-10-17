from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

from app.models import Job


class JobRepository:
    def get(self, session: Session, job_id: int) -> Job | None:
        return session.get(Job, job_id)

    @staticmethod
    def _apply_filters(
        stmt: Select,
        *,
        source: str | None,
        company: str | None,
        location: str | None,
        q: str | None,
    ) -> Select:
        if source is not None:
            stmt = stmt.where(Job.source == source)
        if company is not None:
            stmt = stmt.where(Job.company == company)
        if location is not None:
            stmt = stmt.where(Job.location == location)
        if q is not None:
            stmt = stmt.where(Job.title.ilike(f"%{q}%"))
        return stmt

    def list(
        self,
        session: Session,
        *,
        limit: int,
        offset: int,
        source: str | None = None,
        company: str | None = None,
        location: str | None = None,
        q: str | None = None,
    ) -> list[Job]:
        stmt = self._apply_filters(
            select(Job), source=source, company=company, location=location, q=q
        ).order_by(Job.id)
        stmt = stmt.limit(limit).offset(offset)
        return list(session.scalars(stmt))

    def count(
        self,
        session: Session,
        *,
        source: str | None = None,
        company: str | None = None,
        location: str | None = None,
        q: str | None = None,
    ) -> int:
        stmt = self._apply_filters(
            select(func.count()).select_from(Job),
            source=source,
            company=company,
            location=location,
            q=q,
        )
        return session.scalar(stmt) or 0

    def add(self, session: Session, job: Job) -> Job:
        session.add(job)
        session.flush()
        return job

    def find_by_external_id(
        self, session: Session, *, source: str, external_job_id: str
    ) -> Job | None:
        stmt = select(Job).where(
            Job.source == source, Job.external_job_id == external_job_id
        )
        return session.scalar(stmt)
