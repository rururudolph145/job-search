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
                location="Tokyo",
            )
        )
        session.add(
            Job(
                source="linkedin",
                external_job_id="456",
                title="Data Analyst",
                company=None,
                location=None,
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


def test_list_jobs_q_case_insensitive_substring(client: TestClient) -> None:
    resp = client.get("/jobs", params={"q": "SOFTWARE"})
    body = resp.json()
    assert [item["title"] for item in body["items"]] == ["Software Engineer"]
