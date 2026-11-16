from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Index, Integer, Text, func, text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class Job(Base):
    __tablename__ = "jobs"

    # BIGINT on Postgres (the spec's mandated PK type); plain INTEGER on SQLite so
    # the rowid autoincrements in unit tests (SQLite only auto-increments an
    # ``INTEGER PRIMARY KEY`` — a ``BIGINT`` PK does not).
    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        primary_key=True,
        autoincrement=True,
    )
    source: Mapped[str] = mapped_column(Text, nullable=False)
    external_job_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    company: Mapped[str | None] = mapped_column(Text, nullable=True)
    location: Mapped[str | None] = mapped_column(Text, nullable=True)
    city: Mapped[str | None] = mapped_column(Text, nullable=True)
    country: Mapped[str | None] = mapped_column(Text, nullable=True)
    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    __table_args__ = (
        # Partial unique identity key. `postgresql_where` (the SQLAlchemy 2.0
        # dialect-option name for a partial index predicate) is emitted by the
        # Postgres DDL compiler but dropped on SQLite (which has no partial
        # indexes); both dialects keep the index UNIQUE and null-tolerant, which
        # is what the unit tests exercise. With the unique index in place, the
        # old non-unique `ix_jobs_source_external_job_id` is redundant — the
        # unique index serves every lookup the old one did.
        Index(
            "uq_jobs_source_external_job_id",
            "source",
            "external_job_id",
            unique=True,
            postgresql_where=text("external_job_id IS NOT NULL"),
        ),
        Index("ix_jobs_last_seen_at", "last_seen_at"),
        Index("ix_jobs_country_city", "country", "city"),
    )
