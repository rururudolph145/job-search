from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Index, Integer, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class CrawlRun(Base):
    """One row per crawl attempt that reached the application.

    ``status`` is ``running`` | ``succeeded`` | ``failed`` | ``skipped_locked``.
    A crashed process leaves a ``running`` row with ``finished_at`` NULL — the
    intended signal that a run died mid-flight (PBI 8 reads it as "unknown").
    """

    __tablename__ = "crawl_runs"

    # Mirrors ``Job.id``: BIGINT on Postgres, INTEGER on SQLite so the rowid
    # autoincrements in unit tests.
    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        primary_key=True,
        autoincrement=True,
    )
    source: Mapped[str] = mapped_column(Text, nullable=False)
    trigger: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created: Mapped[int | None] = mapped_column(Integer, nullable=True)
    seen: Mapped[int | None] = mapped_column(Integer, nullable=True)
    skipped_no_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (Index("ix_crawl_runs_started_at", "started_at"),)
