from jobsearch_shared.schemas import HealthResponse


def test_health_response_roundtrip() -> None:
    h = HealthResponse(status="ok")
    assert h.status == "ok"
    assert h.model_dump() == {"status": "ok"}


def test_health_response_from_attributes() -> None:
    class Stub:
        status = "ok"

    h = HealthResponse.model_validate(Stub())
    assert h.status == "ok"
