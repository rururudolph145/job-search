"""Value objects crossing the source→service boundary."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class JobDraft:
    """A listing exactly as a source can know it — no source/timestamps.

    Frozen + slots because this value crosses the source→service boundary and
    nothing should mutate it. Every ``JobDraft`` has a non-empty
    ``external_job_id`` (sources drop id-less dicts before constructing one).
    """

    external_job_id: str
    title: str
    company: str | None
    location: str | None
    url: str
    city: str | None = None
    country: str | None = None
