import pytest
from app.ingestion.policy import UnconfiguredHostError
from app.ingestion.scrapy_settings import build_scrapy_settings


def test_settings_include_politeness_values() -> None:
    s = build_scrapy_settings()
    assert s["DOWNLOAD_DELAY"] == 2.0
    assert s["RANDOMIZE_DOWNLOAD_DELAY"] is True
    assert s["CONCURRENT_REQUESTS"] == 1
    assert s["CONCURRENT_REQUESTS_PER_DOMAIN"] == 1
    assert s["AUTOTHROTTLE_ENABLED"] is True
    assert s["AUTOTHROTTLE_TARGET_CONCURRENCY"] == 1.0
    assert s["AUTOTHROTTLE_MAX_DELAY"] == 30.0


def test_retry_times_is_zero() -> None:
    assert build_scrapy_settings()["RETRY_TIMES"] == 0


def test_robotstxt_obey_is_explicitly_false() -> None:
    # Present AND False: truthiness catches a dropped key and a stale True.
    assert build_scrapy_settings()["ROBOTSTXT_OBEY"] is False


def test_log_enabled_mirrors_verbose() -> None:
    assert build_scrapy_settings(verbose=True)["LOG_ENABLED"] is True
    assert build_scrapy_settings(verbose=False)["LOG_ENABLED"] is False
    assert build_scrapy_settings(verbose=True)["LOG_LEVEL"] == "INFO"
    assert build_scrapy_settings(verbose=False)["LOG_LEVEL"] == "DEBUG"
    assert build_scrapy_settings(verbose=True)["AUTOTHROTTLE_DEBUG"] is True
    assert build_scrapy_settings(verbose=False)["AUTOTHROTTLE_DEBUG"] is False


def test_item_pipelines_and_spider_middlewares_registered() -> None:
    s = build_scrapy_settings()
    assert s["ITEM_PIPELINES"] == {
        "app.ingestion.sources.google_careers._CrawlItemsPipeline": 1
    }
    assert s["SPIDER_MIDDLEWARES"] == {
        "app.ingestion.middleware.PolicyGuardMiddleware": 543
    }


def test_unconfigured_source_host_fails_loudly() -> None:
    # A second source without a budget must fail at settings build, not crawl on
    # permissive defaults (review focus 4).
    with pytest.raises(UnconfiguredHostError):
        build_scrapy_settings(source_url="https://jobs.example.com/sitemap")
