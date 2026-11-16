"""Postgres-only migration test for 0005 (jobs.city, jobs.country, index).

Opt-in via the `ingest` marker (make test-integration): it inspects the real
Postgres schema after `make migrate`, not an in-memory SQLite build.
"""

import os
from collections.abc import Iterator

import pytest
from sqlalchemy import Engine, create_engine, inspect

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


def test_jobs_has_nullable_city_and_country(engine: Engine) -> None:
    insp = inspect(engine)
    cols = {c["name"]: c for c in insp.get_columns("jobs")}
    assert "city" in cols
    assert "country" in cols
    assert cols["city"]["nullable"] is True
    assert cols["country"]["nullable"] is True


def test_jobs_has_country_city_index(engine: Engine) -> None:
    insp = inspect(engine)
    index_names = {ix["name"] for ix in insp.get_indexes("jobs")}
    assert "ix_jobs_country_city" in index_names
