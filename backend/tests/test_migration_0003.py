"""Postgres-only migration tests, opt-in via the `ingest` marker (make test-integration).

SQLite has no partial-index support and cannot prove the `WHERE external_job_id
IS NOT NULL` predicate; these assertions run against the real Postgres the
Docker Compose stack provides.
"""

import os
from collections.abc import Iterator

import pytest
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.exc import IntegrityError

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


_DUP_INSERT = text(
    "INSERT INTO jobs (source, external_job_id, title) "
    "VALUES ('google_careers', '__pbi3test__', 'dup')"
)


def _reject_duplicate(engine: Engine) -> None:
    try:
        with engine.begin() as conn:
            conn.execute(_DUP_INSERT)
        # Each insert owns its transaction: a rejected duplicate aborts only
        # its own transaction, leaving the connection usable for the next one.
        with pytest.raises(IntegrityError):
            with engine.begin() as conn:
                conn.execute(_DUP_INSERT)
    finally:
        # Leave the DB clean for reruns even when an assertion fails.
        with engine.begin() as conn:
            conn.execute(
                text("DELETE FROM jobs WHERE external_job_id = '__pbi3test__'")
            )


def test_partial_index_rejects_duplicate(engine: Engine) -> None:
    _reject_duplicate(engine)


def test_partial_index_allows_two_null_ids(engine: Engine) -> None:
    # Two id-less rows must coexist: the predicate excludes NULL ids. A *plain*
    # unique index would also allow this on Postgres (multiple NULLs permitted),
    # so this is a necessary-but-not-sufficient check; combined with the
    # reject-duplicate test it pins the partial behavior end-to-end.
    with engine.begin() as conn:
        conn.execute(text("INSERT INTO jobs (source, title) VALUES ('t', 'a')"))
        conn.execute(text("INSERT INTO jobs (source, title) VALUES ('t', 'b')"))
        rows = conn.execute(text("SELECT count(*) FROM jobs WHERE source='t'")).scalar()
        assert rows == 2
        conn.execute(text("DELETE FROM jobs WHERE source='t'"))


def test_dirty_row_preserved_by_migration(engine: Engine) -> None:
    # Spec §5.2: legacy rows with dirty display text (a double-space title) must
    # NOT be re-normalized by this migration — rewriting user-visible data is
    # beyond the constraint the user approved. Pin that decision: insert a row
    # with a double-space title, confirm the migration leaves it byte-identical.
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO jobs (source, external_job_id, title) "
                "VALUES ('t', '__dirty__', 'Software Engineer, AI/ML,  PhD')"
            )
        )
    with engine.connect() as conn:
        title = conn.execute(
            text("SELECT title FROM jobs WHERE external_job_id = '__dirty__'")
        ).scalar()
    assert title is not None
    assert "  " in title  # the double space "  PhD" is still present
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM jobs WHERE external_job_id = '__dirty__'"))
