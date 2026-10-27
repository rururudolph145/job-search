"""Scrapy spider middleware enforcing the crawl's permitted scope (§6.3.1)."""

from __future__ import annotations

from collections.abc import AsyncIterable, AsyncIterator

import scrapy


class PolicyViolation(Exception):
    """A request escaped the crawl's permitted scope. Never swallowed."""


# careers.google.com 301s every job page to www.google.com/about/careers/…, and
# Scrapy re-issues that request with `redirected_from` in its meta. The redirect
# target is permitted only when it maps from an in-scope loc — never by path
# prefix, which would make any careers-subtree URL fetchable and contradict
# §6.1's "<loc>-only" scope.
REDIRECT_META_KEY = "redirected_from"


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
        # Snapshot ``allowed`` before consuming ``result``: reading it inside the
        # loop would reintroduce the partial-scope window this guard exists to
        # close, because the source generator is adapted asynchronously.
        allowed: set[str] = set(getattr(spider, "allowed_sitemap_urls", set()))
        allowed.update(spider.start_urls)
        async for request in result:
            if not self._is_permitted(request, allowed):
                raise PolicyViolation(
                    f"crawl requested {request.url!r}, which is outside the "
                    "permitted sitemap scope"
                )
            yield request

    @staticmethod
    def _is_permitted(request: scrapy.Request, allowed: set[str]) -> bool:
        if request.url in allowed:
            return True
        # A redirect target is still the same job request, so it is legal only
        # when it was redirected from a URL that is itself in scope.
        origin = request.meta.get(REDIRECT_META_KEY)
        return isinstance(origin, str) and origin in allowed
