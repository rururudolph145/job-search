"""Thin re-exports of shared contracts.

Domain schemas live in ``jobsearch_shared`` and are re-exported here so the
backend can import from ``app.schemas`` without a direct dependency on the
shared package's import path in application code.
"""

from jobsearch_shared.schemas import HealthResponse

__all__ = ["HealthResponse"]
