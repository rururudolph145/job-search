from app.models import Base, Job
from app.schemas import JobResponse
from sqlalchemy import create_engine
from sqlalchemy.orm import Session


def test_job_response_validates_orm_instance() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    job = Job(
        source="google_careers",
        external_job_id="123",
        title="Software Engineer",
        company=None,
        location="Tokyo",
    )
    with Session(engine) as session:
        session.add(job)
        session.commit()

        # Validate while the instance is still bound to the open session —
        # after commit() the attributes are expired and a detached instance
        # cannot refresh them.
        resp = JobResponse.model_validate(job, from_attributes=True)

    assert resp.title == "Software Engineer"
    assert resp.company is None
    assert resp.city is None
    assert resp.country is None
