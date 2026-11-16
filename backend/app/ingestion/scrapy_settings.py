"""Politeness + collection settings for the crawl (§6.3).

Pure: returns a plain dict and imports nothing from Scrapy, so it is trivially
testable. ``GoogleCareersSource._make_process`` wraps the result in a Scrapy
``Settings``. The policy guard is registered by dotted path — this module never
imports it.
"""

from __future__ import annotations

from app.ingestion.policy import budget_for


def build_scrapy_settings(
    *,
    verbose: bool = False,
    source_url: str = "https://careers.google.com/jobs/sitemap",
) -> dict[str, object]:
    """Politeness + collection pipeline for the google_careers crawl."""
    budget = budget_for(source_url)
    return {
        "ITEM_PIPELINES": {
            "app.ingestion.sources.google_careers._CrawlItemsPipeline": 1
        },
        "SPIDER_MIDDLEWARES": {"app.ingestion.middleware.PolicyGuardMiddleware": 543},
        # PBI 2 disabled logging entirely when not verbose; preserved exactly.
        "LOG_ENABLED": verbose,
        "LOG_LEVEL": "INFO" if verbose else "DEBUG",
        "DOWNLOAD_DELAY": budget.download_delay,
        "RANDOMIZE_DOWNLOAD_DELAY": True,
        "CONCURRENT_REQUESTS": 1,
        "CONCURRENT_REQUESTS_PER_DOMAIN": budget.concurrent_requests_per_domain,
        "AUTOTHROTTLE_ENABLED": True,
        "AUTOTHROTTLE_TARGET_CONCURRENCY": budget.autothrottle_target_concurrency,
        "AUTOTHROTTLE_MAX_DELAY": budget.autothrottle_max_delay,
        "AUTOTHROTTLE_DEBUG": verbose,
        # Retry/backoff is PBI 7 and must not stack here.
        "RETRY_TIMES": 0,
        # Present AND False: a future Scrapy flipping its default must not
        # silently empty the crawl. Scope is enforced structurally by the guard.
        "ROBOTSTXT_OBEY": False,
    }
