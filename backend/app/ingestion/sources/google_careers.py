"""GoogleCareersSource — wraps a Scrapy crawl and yields validated JobDrafts."""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from typing import Any

from scrapy.crawler import CrawlerProcess
from scrapy.utils.project import get_project_settings

from app.ingestion.drafts import JobDraft
from app.ingestion.normalize import (
    normalize_company,
    normalize_external_id,
    normalize_location,
    normalize_title,
)
from app.ingestion.spiders.google_careers import GoogleCareersSpider


class FetchError(Exception):
    """Raised when the underlying crawl fails (sitemap unreachable, network down)."""


class GoogleCareersSource:
    """A ``JobSource`` over Google Careers' public sitemap."""

    name: str = "google_careers"

    def __init__(self, verbose: bool = False) -> None:
        self.verbose = verbose
        self.skipped_no_id = 0

    def fetch(self) -> Iterator[JobDraft]:
        spider = GoogleCareersSpider()
        for raw in self._run_crawl(spider):
            external_job_id = normalize_external_id(raw.get("external_job_id") or "")
            if not external_job_id:
                # Id-less page: un-parseable for this source. This is a hard-coded
                # policy at the source layer — see spec §4.3 (id-less jobs gap).
                # `jobs.external_job_id` is nullable and the PBI-3 partial index
                # exists precisely for that case, but no source yet produces a
                # legitimately id-less job, so this guard drops the dict entirely.
                self.skipped_no_id += 1
                continue
            draft = JobDraft(
                external_job_id=external_job_id,
                title=normalize_title(raw.get("title") or ""),
                location=normalize_location(raw.get("location")),
                company=normalize_company(raw.get("company")),
                url=raw.get("url") or "",
            )
            yield draft

    def _make_process(self) -> CrawlerProcess:
        """Build the Scrapy process with this source's verbosity settings."""
        settings = get_project_settings()
        settings.set(
            "ITEM_PIPELINES",
            {"app.ingestion.sources.google_careers._CrawlItemsPipeline": 1},
        )
        if self.verbose:
            settings.set("LOG_LEVEL", "INFO")
        else:
            settings.set("LOG_ENABLED", False)
        return CrawlerProcess(settings)

    def _run_crawl(self, spider: object) -> Iterable[dict[str, Any]]:
        """Run the real Scrapy crawl. Replaced wholesale by fakes in tests."""
        _CRAWLED_ITEMS.clear()
        process = self._make_process()
        process.crawl(GoogleCareersSpider)
        try:
            process.start()
        except Exception as exc:
            # Sitemap unreachable / network down: surface as a distinct error so the
            # CLI can tell a failed fetch from an empty-but-successful crawl (§5).
            raise FetchError(f"sitemap unreachable: {exc}") from exc
        yield from _CRAWLED_ITEMS


def make_google_careers_source(verbose: bool = False) -> GoogleCareersSource:
    """Factory wiring the production Scrapy runner into a GoogleCareersSource."""
    return GoogleCareersSource(verbose=verbose)


# Item collector: the spider yields plain dicts, and Scrapy routes every yielded
# item through an ITEM_PIPELINES entry. `_make_process` registers this class by
# its full dotted path, so `process_item` appends each dict into `_CRAWLED_ITEMS`,
# which `_run_crawl` drains after `process.start()` returns.
_CRAWLED_ITEMS: list[dict[str, Any]] = []


class _CrawlItemsPipeline:
    def process_item(self, item: dict[str, Any], spider: object) -> dict[str, Any]:
        _CRAWLED_ITEMS.append(item)
        return item
