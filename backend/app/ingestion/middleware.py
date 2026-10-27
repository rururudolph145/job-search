"""Scrapy spider middleware enforcing the crawl's permitted scope (§6.3.1)."""

from __future__ import annotations

from collections.abc import AsyncIterable, AsyncIterator

import scrapy


class PolicyViolation(Exception):
    """A request escaped the crawl's permitted scope. Never swallowed."""


# careers.google.com 301s every job page to this host, and Scrapy re-issues the
# request on redirect, so the guard would otherwise refuse every live crawl.
# Scoped to the careers subtree: www.google.com at large stays out of bounds.
DECLARED_REDIRECT_PREFIXES: tuple[str, ...] = ("https://www.google.com/about/careers/",)


class PolicyGuardMiddleware:
    """Raise ``PolicyViolation`` if a request's URL is outside the permitted scope.

    Uses ``process_spider_output`` (raising stops the crawl) rather than the
    downloader hook ``allow_request`` (which merely skips the request — a silent
    drop indistinguishable from an empty feed).

    Must be an async generator: Scrapy buffers spider output asynchronously and
    rejects a sync ``process_spider_output`` when the middleware is registered.
    """

    async def process_spider_output(
        self,
        response: scrapy.http.Response,
        result: AsyncIterable[scrapy.Request],
        spider: scrapy.Spider,
    ) -> AsyncIterator[scrapy.Request]:
        # The permitted set is the sitemap's accepted <loc>s plus the sitemap URL
        # itself. The sitemap request is a start_url, not spider output, so this
        # guard never sees it in practice — but including it keeps any re-request
        # of the feed legal.
        allowed: set[str] = set(getattr(spider, "allowed_sitemap_urls", set()))
        allowed.update(spider.start_urls)
        async for request in result:
            if not self._is_permitted(request.url, allowed):
                raise PolicyViolation(
                    f"crawl requested {request.url!r}, which is outside the "
                    "permitted sitemap scope"
                )
            yield request

    @staticmethod
    def _is_permitted(url: str, allowed: set[str]) -> bool:
        if url in allowed:
            return True
        return url.startswith(DECLARED_REDIRECT_PREFIXES)
