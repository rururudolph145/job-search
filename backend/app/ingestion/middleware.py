"""Scrapy spider middleware enforcing the crawl's permitted scope (§6.3.1)."""

from __future__ import annotations

from collections.abc import Iterable

import scrapy


class PolicyViolation(Exception):
    """A request escaped the crawl's permitted scope. Never swallowed."""


class PolicyGuardMiddleware:
    """Raise ``PolicyViolation`` if a request's URL is outside the permitted scope.

    Uses ``process_spider_output`` (raising stops the crawl) rather than the
    downloader hook ``allow_request`` (which merely skips the request — a silent
    drop indistinguishable from an empty feed).
    """

    def process_spider_output(
        self,
        response: scrapy.http.Response,
        result: Iterable[scrapy.Request],
        spider: scrapy.Spider,
    ) -> Iterable[scrapy.Request]:
        # The permitted set is the sitemap's accepted <loc>s plus the sitemap URL
        # itself. The sitemap request is a start_url, not spider output, so this
        # guard never sees it in practice — but including it keeps any re-request
        # of the feed legal.
        allowed: set[str] = set(getattr(spider, "allowed_sitemap_urls", set()))
        allowed.update(spider.start_urls)
        for request in result:
            if request.url not in allowed:
                raise PolicyViolation(
                    f"crawl requested {request.url!r}, which is outside the "
                    "permitted sitemap scope"
                )
            yield request
