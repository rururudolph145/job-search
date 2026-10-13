"""JobSource protocol and its concrete implementations."""

from app.ingestion.sources.base import JobSource
from app.ingestion.sources.google_careers import GoogleCareersSource

__all__ = ["JobSource", "GoogleCareersSource"]
