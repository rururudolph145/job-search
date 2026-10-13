"""Opt-in network test: run a real crawl, capped at one item.

Excluded from the default suite via `-m "not ingest"` (see marker in
pyproject.toml). Run with `make test-integration`.
"""

import pytest
from app.ingestion.sources.google_careers import make_google_careers_source


@pytest.mark.ingest
def test_real_crawl_yields_nonempty() -> None:
    source = make_google_careers_source()
    drafts = list(source.fetch())
    assert drafts  # a real crawl of the sitemap reaches at least one Tokyo SWE item
