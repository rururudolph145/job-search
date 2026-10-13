"""The seam an ingestion source must satisfy."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Protocol

from app.ingestion.drafts import JobDraft


class JobSource(Protocol):
    name: str  # the ``jobs.source`` slug the service writes

    def fetch(self) -> Iterator[JobDraft]: ...
