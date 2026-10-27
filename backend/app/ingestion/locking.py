"""Cross-process overlap protection for the crawl (§6.6)."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import text
from sqlalchemy.orm import Session

# 'JS' + PBI 6; arbitrary, fixed, documented. Shared by every jobsearch crawl.
LOCK_KEY = 0x4A53_0006


@contextmanager
def ingestion_lock(session: Session) -> Iterator[bool]:
    """Yield True if this process holds the crawl lock.

    Postgres: ``pg_try_advisory_lock`` / released with ``pg_advisory_unlock`` on
    the same session in ``finally``; the lock also dies with the connection.
    SQLite (tests): always yields True — no cross-process concurrency to guard.
    """
    if session.get_bind().dialect.name != "postgresql":
        yield True
        return

    acquired = bool(
        session.execute(
            text("SELECT pg_try_advisory_lock(:key)"), {"key": LOCK_KEY}
        ).scalar()
    )
    try:
        yield acquired
    finally:
        # Only release a lock this call acquired — unlocking another session's
        # lock would break mutual exclusion.
        if acquired:
            session.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": LOCK_KEY})
