import pytest
import scrapy
from app.ingestion.middleware import PolicyGuardMiddleware, PolicyViolation
from scrapy.exceptions import IgnoreRequest


class FakeSpider(scrapy.Spider):
    name = "fake"
    start_urls = ["https://careers.google.com/jobs/sitemap"]
    allowed_sitemap_urls: set[str]


def _request(url: str) -> scrapy.Request:
    return scrapy.Request(url)


def _response() -> scrapy.http.HtmlResponse:
    return scrapy.http.HtmlResponse(
        url="https://careers.google.com/jobs/sitemap", body=b""
    )


def test_passes_sitemap_member_urls() -> None:
    spider = FakeSpider()
    spider.allowed_sitemap_urls = {"https://careers.google.com/jobs/results/1-a/"}
    mw = PolicyGuardMiddleware()
    reqs = list(
        mw.process_spider_output(
            _response(),
            [_request("https://careers.google.com/jobs/results/1-a/")],
            spider,
        )
    )
    assert [r.url for r in reqs] == ["https://careers.google.com/jobs/results/1-a/"]


def test_raises_on_non_member_url() -> None:
    spider = FakeSpider()
    spider.allowed_sitemap_urls = {"https://careers.google.com/jobs/results/1-a/"}
    mw = PolicyGuardMiddleware()
    with pytest.raises(PolicyViolation):
        list(
            mw.process_spider_output(
                _response(),
                [_request("https://careers.google.com/jobs/results/999-other/")],
                spider,
            )
        )


def test_violation_is_not_a_silent_drop() -> None:
    # An IgnoreRequest would skip the request and let the crawl "succeed" empty.
    spider = FakeSpider()
    spider.allowed_sitemap_urls = set()
    mw = PolicyGuardMiddleware()
    with pytest.raises(PolicyViolation) as excinfo:
        list(
            mw.process_spider_output(
                _response(),
                [_request("https://careers.google.com/jobs/results/2-b/")],
                spider,
            )
        )
    assert not isinstance(excinfo.value, IgnoreRequest)
    assert "https://careers.google.com/jobs/results/2-b/" in str(excinfo.value)


def test_start_url_is_always_permitted() -> None:
    spider = FakeSpider()
    spider.allowed_sitemap_urls = set()
    mw = PolicyGuardMiddleware()
    reqs = list(
        mw.process_spider_output(
            _response(), [_request("https://careers.google.com/jobs/sitemap")], spider
        )
    )
    assert len(reqs) == 1


def test_raises_on_first_non_member_and_stops() -> None:
    spider = FakeSpider()
    spider.allowed_sitemap_urls = {"https://careers.google.com/jobs/results/1-a/"}
    mw = PolicyGuardMiddleware()
    with pytest.raises(PolicyViolation):
        list(
            mw.process_spider_output(
                _response(),
                [
                    _request("https://careers.google.com/jobs/results/1-a/"),
                    _request("https://careers.google.com/jobs/results/2-b/"),
                ],
                spider,
            )
        )
