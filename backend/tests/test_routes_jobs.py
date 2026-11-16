from collections.abc import Iterator

import pytest
from app.db import engine as engine_mod
from app.main import app
from app.models import Base, Job
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool


@pytest.fixture()
def client(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    # StaticPool keeps one connection so the in-memory DB survives; the
    # dependency runs in FastAPI's worker thread, hence check_same_thread=False.
    test_engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(test_engine)
    with Session(test_engine) as session:
        session.add(
            Job(
                source="google_careers",
                external_job_id="123",
                title="Software Engineer",
                company="Google",
                location="Tokyo, Japan",
                city="Tokyo",
                country="JP",
            )
        )
        session.add(
            Job(
                source="linkedin",
                external_job_id="456",
                title="Data Analyst",
                company=None,
                location="New York, NY, USA",
                city="New York",
                country="US",
            )
        )
        session.commit()
    monkeypatch.setattr(engine_mod, "engine", test_engine)
    yield TestClient(app)


def test_list_jobs_returns_envelope(client: TestClient) -> None:
    resp = client.get("/jobs")
    assert resp.status_code == 200
    body = resp.json()
    assert set(body.keys()) == {"items", "total"}
    assert body["total"] == 2
    assert [item["title"] for item in body["items"]] == [
        "Software Engineer",
        "Data Analyst",
    ]


def test_list_jobs_source_filter(client: TestClient) -> None:
    resp = client.get("/jobs", params={"source": "linkedin"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 1
    assert [item["title"] for item in body["items"]] == ["Data Analyst"]


def test_list_jobs_country_filter(client: TestClient) -> None:
    resp = client.get("/jobs", params={"country": "jp"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 1
    assert [item["title"] for item in body["items"]] == ["Software Engineer"]
    assert body["items"][0]["country"] == "JP"


def test_list_jobs_city_filter(client: TestClient) -> None:
    resp = client.get("/jobs", params={"city": "New York"})
    body = resp.json()
    assert body["total"] == 1
    assert [item["title"] for item in body["items"]] == ["Data Analyst"]


def test_list_jobs_country_and_city_combine(client: TestClient) -> None:
    resp = client.get("/jobs", params={"country": "JP", "city": "New York"})
    assert resp.json() == {"items": [], "total": 0}


def test_list_jobs_q_case_insensitive_substring(client: TestClient) -> None:
    resp = client.get("/jobs", params={"q": "SOFTWARE"})
    body = resp.json()
    assert [item["title"] for item in body["items"]] == ["Software Engineer"]


def test_list_empty_returns_zero_envelope(client: TestClient) -> None:
    resp = client.get("/jobs", params={"source": "nonexistent"})
    assert resp.status_code == 200
    assert resp.json() == {"items": [], "total": 0}


def test_list_total_reflects_filters(client: TestClient) -> None:
    # q="software" matches 1 row, but total must be 1 (not the 2-row table total).
    resp = client.get("/jobs", params={"q": "software"})
    body = resp.json()
    assert body["total"] == 1
    assert len(body["items"]) == 1


def test_list_limit_bounds(client: TestClient) -> None:
    assert client.get("/jobs", params={"limit": "0"}).status_code == 422
    assert client.get("/jobs", params={"limit": "101"}).status_code == 422
    assert client.get("/jobs", params={"offset": "-1"}).status_code == 422


def test_get_job_returns_row(client: TestClient) -> None:
    # First find an existing id via the list endpoint.
    listings = client.get("/jobs").json()
    some_id = listings["items"][0]["id"]

    resp = client.get(f"/jobs/{some_id}")
    assert resp.status_code == 200
    assert resp.json()["id"] == some_id


def test_get_job_not_found(client: TestClient) -> None:
    resp = client.get("/jobs/999999999")
    assert resp.status_code == 404
    assert resp.json() == {"detail": "Job not found"}
