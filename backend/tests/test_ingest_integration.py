"""Opt-in network test: run a real crawl, capped at one item.

Excluded from the default suite via `-m "not ingest"` (see marker in
pyproject.toml). Run with `make test-integration`.

The production crawl must stay polite (1 request / ~2 s, autothrottle), which
makes a full sitemap pass take ~50 minutes. This test only needs to prove the
*real* path — sitemap → policy guard → redirect → tuple extraction — reaches at
least one Japan job, so it closes the spider after the first scraped item. The
politeness knobs themselves are pinned by the unit suite
(test_google_careers_source.py), not by this gate.
"""

import pytest
from app.ingestion.drafts import JobDraft
from app.ingestion.normalize import (
    normalize_company,
    normalize_country,
    normalize_external_id,
    normalize_location,
    normalize_title,
)
from app.ingestion.scrapy_settings import build_scrapy_settings
from app.ingestion.sources.google_careers import _CRAWLED_ITEMS
from app.ingestion.spiders.google_careers import SITEMAP_URL, GoogleCareersSpider
from scrapy import signals
from scrapy.crawler import CrawlerProcess
from scrapy.settings import Settings


@pytest.mark.ingest
def test_real_crawl_yields_nonempty() -> None:
    settings = Settings(build_scrapy_settings(source_url=SITEMAP_URL))
    process = CrawlerProcess(settings)
    crawler = process.create_crawler(GoogleCareersSpider)

    def _stop_after_first_item(
        item: dict[str, object], response: object, spider: object
    ) -> None:
        # One scraped item proves the live path yields a Japan job. Close early
        # so the test does not wait ~50 minutes for the whole sitemap.
        # close_spider is idempotent; repeated calls before shutdown are no-ops.
        crawler.engine.close_spider(crawler.spider, "test: first item reached")

    crawler.signals.connect(_stop_after_first_item, signal=signals.item_scraped)
    process.crawl(crawler)
    process.start()

    drafts: list[JobDraft] = []
    for raw in _CRAWLED_ITEMS:
        external_job_id = normalize_external_id(str(raw.get("external_job_id") or ""))
        if not external_job_id:
            continue
        drafts.append(
            JobDraft(
                external_job_id=external_job_id,
                title=normalize_title(str(raw.get("title") or "")),
                location=normalize_location(raw.get("location")),
                company=normalize_company(raw.get("company")),
                url=str(raw.get("url") or ""),
                city=normalize_location(raw.get("city")),
                country=normalize_country(raw.get("country")),
            )
        )

    assert drafts, "the live crawl reached no Japan job page"
    assert drafts[0].country == "JP"
    assert drafts[0].city
