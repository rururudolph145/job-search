from typing import Annotated

import pytest
from app.db import engine as engine_mod
from app.db.engine import DEFAULT_DB_URL, get_db
from app.models import Base
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session


def test_database_url_default() -> None:
    assert (
        DEFAULT_DB_URL
        == "postgresql+psycopg://jobsearch:jobsearch@localhost:5432/jobsearch"
    )


def test_database_url_respects_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://u:p@h:5432/x")
    assert engine_mod.database_url() == "postgresql+psycopg://u:p@h:5432/x"


def test_get_session_yields_session(monkeypatch: pytest.MonkeyPatch) -> None:
    test_engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(test_engine)
    monkeypatch.setattr(engine_mod, "engine", test_engine)

    with engine_mod.get_session() as s:
        assert s is not None


def test_get_db_works_as_fastapi_dependency(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    test_engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(test_engine)
    monkeypatch.setattr(engine_mod, "engine", test_engine)

    closed: list[Session] = []
    real_close = Session.close

    def spy_close(self: Session) -> None:
        closed.append(self)
        real_close(self)

    monkeypatch.setattr(Session, "close", spy_close)

    probe = FastAPI()

    @probe.get("/probe")
    def probe_route(
        session: Annotated[Session, Depends(get_db)],
    ) -> dict[str, bool]:
        return {"ok": session.execute(text("SELECT 1")).scalar() == 1}

    with TestClient(probe) as client:
        resp = client.get("/probe")

    assert resp.status_code == 200
    assert resp.json() == {"ok": True}
    assert len(closed) == 1
