import pytest
from app.db import engine as engine_mod
from app.db.engine import DEFAULT_DB_URL
from app.models import Base
from sqlalchemy import create_engine


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
