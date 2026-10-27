from collections.abc import AsyncIterable, AsyncIterator, Iterable

import pytest
import scrapy
from app.ingestion.middleware import PolicyGuardMiddleware, PolicyViolation
from scrapy.core.spidermw import SpiderMiddlewareManager
from scrapy.exceptions import IgnoreRequest
from scrapy.utils.test import get_crawler


class FakeSpider(scrapy.Spider):
    name = "fake"
    start_urls = ["https://careers.google.com/jobs/sitemap"]
    allowed_sitemap_urls: set[str]


def _request(url: str, meta: dict[str, object] | None = None) -> scrapy.Request:
    return scrapy.Request(url, meta=meta)


def _response() -> scrapy.http.HtmlResponse:
    return scrapy.http.HtmlResponse(
        url="https://careers.google.com/jobs/sitemap", body=b""
    )


async def _as_async(
    items: Iterable[scrapy.Request],
) -> AsyncIterable[scrapy.Request]:
    """Feed a sync list through the hook, which now consumes an async stream."""
    for item in items:
        yield item


async def _collect(gen: AsyncIterator[scrapy.Request]) -> list[scrapy.Request]:
    return [request async for request in gen]


async def test_passes_sitemap_member_urls() -> None:
    spider = FakeSpider()
    spider.allowed_sitemap_urls = {"https://careers.google.com/jobs/results/1-a/"}
    mw = PolicyGuardMiddleware()
    reqs = await _collect(
        mw.process_spider_output(
            _response(),
            _as_async([_request("https://careers.google.com/jobs/results/1-a/")]),
            spider,
        )
    )
    assert [r.url for r in reqs] == ["https://careers.google.com/jobs/results/1-a/"]


async def test_raises_on_non_member_url() -> None:
    spider = FakeSpider()
    spider.allowed_sitemap_urls = {"https://careers.google.com/jobs/results/1-a/"}
    mw = PolicyGuardMiddleware()
    with pytest.raises(PolicyViolation):
        await _collect(
            mw.process_spider_output(
                _response(),
                _as_async(
                    [_request("https://careers.google.com/jobs/results/999-other/")]
                ),
                spider,
            )
        )


async def test_violation_is_not_a_silent_drop() -> None:
    # An IgnoreRequest would skip the request and let the crawl "succeed" empty.
    spider = FakeSpider()
    spider.allowed_sitemap_urls = set()
    mw = PolicyGuardMiddleware()
    with pytest.raises(PolicyViolation) as excinfo:
        await _collect(
            mw.process_spider_output(
                _response(),
                _as_async([_request("https://careers.google.com/jobs/results/2-b/")]),
                spider,
            )
        )
    assert not isinstance(excinfo.value, IgnoreRequest)
    assert "https://careers.google.com/jobs/results/2-b/" in str(excinfo.value)


async def test_start_url_is_always_permitted() -> None:
    spider = FakeSpider()
    spider.allowed_sitemap_urls = set()
    mw = PolicyGuardMiddleware()
    reqs = await _collect(
        mw.process_spider_output(
            _response(),
            _as_async([_request("https://careers.google.com/jobs/sitemap")]),
            spider,
        )
    )
    assert len(reqs) == 1


@pytest.mark.skip(reason="superseded: prefix admission removed")
async def test_permits_declared_redirect_target() -> None:
    """careers.google.com 301s every job URL to www.google.com/about/careers.

    The redirect also re-issues the request, so the guard sees the target URL.
    It must stay legal for a sitemap <loc> — otherwise no live crawl can finish.
    """
    spider = FakeSpider()
    spider.allowed_sitemap_urls = set()
    mw = PolicyGuardMiddleware()
    redirect_target = (
        "https://www.google.com/about/careers/applications"
        "/jobs/results/123-software-engineer/"
    )
    reqs = await _collect(
        mw.process_spider_output(
            _response(), _as_async([_request(redirect_target)]), spider
        )
    )
    assert [r.url for r in reqs] == [redirect_target]


@pytest.mark.skip(
    reason="superseded: vacuous; see test_refuses_careers_subtree_url_without_an_in_scope_origin"
)
async def test_redirect_scope_does_not_open_unrelated_urls() -> None:
    """Only the declared careers prefix is admitted, not www.google.com at large."""
    spider = FakeSpider()
    spider.allowed_sitemap_urls = set()
    mw = PolicyGuardMiddleware()
    with pytest.raises(PolicyViolation):
        await _collect(
            mw.process_spider_output(
                _response(),
                _as_async([_request("https://www.google.com/search?q=engineer")]),
                spider,
            )
        )


def test_registers_with_scrapy_middleware_manager() -> None:
    """Scrapy rejects a sync `process_spider_output` at registration time.

    Scrapy 2.19 buffers spider output asynchronously, so the hook must be an
    async generator. The direct-call tests above bypass the middleware manager
    and so could not catch a non-async hook; this one registers the guard the
    way `build_scrapy_settings` does.
    """
    crawler = get_crawler(FakeSpider)
    crawler.spider = FakeSpider()
    # Raises TypeError if the hook is not async-aware.
    SpiderMiddlewareManager(PolicyGuardMiddleware(), crawler=crawler)


async def test_raises_on_first_non_member_and_stops() -> None:
    spider = FakeSpider()
    spider.allowed_sitemap_urls = {"https://careers.google.com/jobs/results/1-a/"}
    mw = PolicyGuardMiddleware()
    with pytest.raises(PolicyViolation):
        await _collect(
            mw.process_spider_output(
                _response(),
                _as_async(
                    [
                        _request("https://careers.google.com/jobs/results/1-a/"),
                        _request("https://careers.google.com/jobs/results/2-b/"),
                    ]
                ),
                spider,
            )
        )


async def test_raises_on_late_violation_after_many_permitted() -> None:
    """A long permitted prefix must not defer or swallow a later violation."""
    spider = FakeSpider()
    legit = [
        f"https://careers.google.com/jobs/results/{i}-software-engineer/"
        for i in range(20)
    ]
    spider.allowed_sitemap_urls = set(legit)
    mw = PolicyGuardMiddleware()
    requests = [_request(u) for u in legit] + [_request("https://evil.example/x")]
    with pytest.raises(PolicyViolation):
        await _collect(
            mw.process_spider_output(_response(), _as_async(requests), spider)
        )


async def test_empty_sitemap_yields_nothing_without_raising() -> None:
    """Zero matching <loc>s is a clean empty crawl, not an error."""
    spider = FakeSpider()
    spider.allowed_sitemap_urls = set()
    mw = PolicyGuardMiddleware()
    passed = await _collect(
        mw.process_spider_output(_response(), _as_async([]), spider)
    )
    assert passed == []


async def test_permits_the_redirected_job_target_only_as_a_declared_mapping() -> None:
    """A redirect target is legal only if it maps from an in-scope loc.

    Permit by mapping, not by path prefix: any careers-subtree URL is otherwise
    fetchable, which makes §6.1's "<loc>-only" claim false and a future
    scope-widening change undetectable by this guard.
    """
    spider = FakeSpider()
    loc = "https://careers.google.com/jobs/results/1-software-engineer/"
    spider.allowed_sitemap_urls = {loc}
    mw = PolicyGuardMiddleware()
    target = (
        "https://www.google.com/about/careers/applications"
        "/jobs/results/1-software-engineer/"
    )
    redirected = _request(target, meta={"redirected_from": str(loc)})
    passed = await _collect(
        mw.process_spider_output(_response(), _as_async([redirected]), spider)
    )
    assert [r.url for r in passed] == [target]


async def test_refuses_careers_subtree_url_without_an_in_scope_origin() -> None:
    """An out-of-scope request that sits under the careers subtree still raises."""
    spider = FakeSpider()
    spider.allowed_sitemap_urls = {"https://careers.google.com/jobs/results/1-a/"}
    mw = PolicyGuardMiddleware()
    with pytest.raises(PolicyViolation):
        await _collect(
            mw.process_spider_output(
                _response(),
                _as_async(
                    [
                        _request(
                            "https://www.google.com/about/careers/applications/"
                            "jobs/results/9-not-a-loc/"
                        )
                    ]
                ),
                spider,
            )
        )
