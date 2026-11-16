"""Source ingestion: fetch listings from permitted feeds into the jobs table."""

from app.ingestion.drafts import JobDraft
from app.ingestion.service import IngestionResult, IngestionService
from app.ingestion.sources import GoogleCareersSource, JobSource

__all__ = [
    "JobDraft",
    "JobSource",
    "GoogleCareersSource",
    "IngestionService",
    "IngestionResult",
]
