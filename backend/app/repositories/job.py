from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Job


class JobRepository:
    def get(self, session: Session, job_id: int) -> Job | None:
        return session.get(Job, job_id)

    def list(self, session: Session, *, limit: int, offset: int) -> list[Job]:
        stmt = select(Job).order_by(Job.id).limit(limit).offset(offset)
        return list(session.scalars(stmt))

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
