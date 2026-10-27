"""Postgres-only advisory-lock mutex test, opt-in via the `ingest` marker.

The SQLite branch of ``ingestion_lock`` always yields True (no cross-process
concurrency there), so mutual exclusion can only be proven against real
Postgres. Run with ``make db-up && make test-integration``.
"""

import os
from collections.abc import Iterator

import pytest
from app.ingestion.locking import ingestion_lock
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.orm import Session

pytestmark = pytest.mark.ingest

DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql+psycopg://jobsearch:jobsearch@localhost:5432/jobsearch",
)


@pytest.fixture()
def engine() -> Iterator[Engine]:
    engine = create_engine(DATABASE_URL)
    yield engine
    engine.dispose()


def _sessions(engine: Engine) -> tuple[Session, Session]:
    return Session(engine), Session(engine)


def test_two_holders_mutually_exclude(engine: Engine) -> None:
    s1, s2 = _sessions(engine)
    try:
        with ingestion_lock(s1) as held1:
            assert held1 is True
            # While the first session holds the lock, a second cannot take it.
            with ingestion_lock(s2) as held2:
                assert held2 is False
        # held1's finally released it; a fresh acquisition succeeds.
        with ingestion_lock(s2) as held3:
            assert held3 is True
    finally:
        # Belt and braces: never leave a session-scoped lock behind.
        s1.execute(text("SELECT pg_advisory_unlock_all()"))
        s2.execute(text("SELECT pg_advisory_unlock_all()"))
        s1.close()
        s2.close()


def test_lock_released_after_normal_exit(engine: Engine) -> None:
    s1, s2 = _sessions(engine)
    try:
        with ingestion_lock(s1) as held1:
            assert held1 is True
        with ingestion_lock(s2) as held2:
            assert held2 is True
    finally:
        s1.execute(text("SELECT pg_advisory_unlock_all()"))
        s2.execute(text("SELECT pg_advisory_unlock_all()"))
        s1.close()
        s2.close()
