from datetime import datetime, timezone

from jobsearch_shared.schemas import JobResponse


def test_job_response_roundtrip() -> None:
    now = datetime(2026, 10, 14, 12, 0, 0, tzinfo=timezone.utc)
    j = JobResponse(
        id=1,
        source="google_careers",
        external_job_id="123",
        title="Software Engineer",
        company="Google",
        location="Tokyo",
        first_seen_at=now,
        last_seen_at=now,
        updated_at=now,
    )
    assert j.id == 1
    assert j.company == "Google"


def test_job_response_from_attributes_and_null_company() -> None:
    class Stub:
        id = 1
        source = "google_careers"
        external_job_id = "123"
        title = "Software Engineer"
        company = None
        location = "Tokyo"
        first_seen_at = datetime(2026, 10, 14, 12, 0, 0, tzinfo=timezone.utc)
        last_seen_at = datetime(2026, 10, 14, 12, 0, 0, tzinfo=timezone.utc)
        updated_at = datetime(2026, 10, 14, 12, 0, 0, tzinfo=timezone.utc)

    j = JobResponse.model_validate(Stub())
    assert j.company is None


def test_job_response_field_set_is_exact() -> None:
    assert set(JobResponse.model_fields) == {
        "id",
        "source",
        "external_job_id",
        "title",
        "company",
        "location",
        "first_seen_at",
        "last_seen_at",
        "updated_at",
    }
