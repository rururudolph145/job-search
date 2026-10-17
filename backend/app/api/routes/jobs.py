from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.db.engine import get_db
from app.repositories.job import JobRepository
from app.schemas import JobListResponse, JobResponse

router = APIRouter(prefix="/jobs", tags=["jobs"])


def _get_repo() -> JobRepository:
    return JobRepository()


@router.get("", response_model=JobListResponse)
async def list_jobs(
    session: Annotated[Session, Depends(get_db)],
    repo: Annotated[JobRepository, Depends(_get_repo)],
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
    source: Annotated[str | None, Query()] = None,
    company: Annotated[str | None, Query()] = None,
    location: Annotated[str | None, Query()] = None,
    q: Annotated[str | None, Query()] = None,
) -> JobListResponse:
    jobs = repo.list(
        session,
        limit=limit,
        offset=offset,
        source=source,
        company=company,
        location=location,
        q=q,
    )
    total = repo.count(session, source=source, company=company, location=location, q=q)
    items = [JobResponse.model_validate(job) for job in jobs]
    return JobListResponse(items=items, total=total)
