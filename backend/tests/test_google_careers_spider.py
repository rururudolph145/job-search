import scrapy
from app.ingestion.spiders.google_careers import GoogleCareersSpider
from scrapy.http import HtmlResponse, TextResponse


def _sitemap_response(urls: list[str]) -> TextResponse:
    body = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
        + "".join(f"<url><loc>{u}</loc></url>" for u in urls)
        + "</urlset>"
    )
    return TextResponse(
        url="https://careers.google.com/jobs/sitemap", body=body.encode()
    )


def _job_response(body_text: str, url: str) -> HtmlResponse:
    return HtmlResponse(url=url, body=body_text.encode(), encoding="utf-8")


def test_sitemap_filters_to_software_engineer_slugs() -> None:
    spider = GoogleCareersSpider()
    sitemap = _sitemap_response(
        [
            "https://careers.google.com/jobs/results/83683003800134342-software-engineering-manager/",
            "https://careers.google.com/jobs/results/123-program-manager/",
            "https://careers.google.com/jobs/results/456-software-engineer/",
        ]
    )
    requests = list(spider.parse(sitemap))
    assert len(requests) == 2
    assert all("software-engineer" in r.url for r in requests)


def test_parse_records_accepted_locs_into_allowed_sitemap_urls() -> None:
    sitemap = _sitemap_response(
        [
            "https://careers.google.com/jobs/results/83683003800134342-software-engineering-manager/",
            "https://careers.google.com/jobs/results/123-program-manager/",
            "https://careers.google.com/jobs/results/456-software-engineer/",
        ]
    )
    spider = GoogleCareersSpider()
    list(spider.parse(sitemap))  # consume the generator
    assert spider.allowed_sitemap_urls == {
        "https://careers.google.com/jobs/results/83683003800134342-software-engineering-manager/",
        "https://careers.google.com/jobs/results/456-software-engineer/",
    }


def test_fresh_spider_starts_with_no_allowed_urls() -> None:
    assert GoogleCareersSpider().allowed_sitemap_urls == set()


def test_job_page_non_japan_tuple_yields_nothing() -> None:
    url = "https://careers.google.com/jobs/results/7-swe/"
    body = (
        "<html><head><title>T</title></head><body><script>"
        '[["Bangalore, India",["Bangalore, India"],null,null,"Bangalore","IN"]]'
        "</script></body></html>"
    )
    spider = GoogleCareersSpider()
    assert list(spider.parse_job(_job_response(body, url))) == []


def test_job_page_without_tuple_yields_nothing() -> None:
    url = "https://careers.google.com/jobs/results/8-swe/"
    body = "<html><body><p>Tokyo, Japan</p></body></html>"
    spider = GoogleCareersSpider()
    assert list(spider.parse_job(_job_response(body, url))) == []


def test_spider_is_scrapy_spider() -> None:
    assert isinstance(GoogleCareersSpider(), scrapy.Spider)


_LOC_BLOB = (
    '<html><head><meta property="og:title" content="SWE Manager"/></head>'
    "<body><script>"
    'x("abc","Google","en-US",[["Tokyo, Japan",["Tokyo, Japan"],null,null,"Tokyo","JP"]],'
    'null,[null,"x"])'
    "</script></body></html>"
)


def test_job_page_extracts_city_and_country_from_tuple() -> None:
    url = "https://careers.google.com/jobs/results/83683003800134342-swe/"
    spider = GoogleCareersSpider()
    result = list(spider.parse_job(_job_response(_LOC_BLOB, url)))
    assert len(result) == 1
    item = result[0]
    assert item["city"] == "Tokyo"
    assert item["country"] == "JP"
    assert item["title"] == "SWE Manager"
    assert item["external_job_id"] == "83683003800134342"


def test_find_location_tuple_returns_none_without_tuple() -> None:
    assert GoogleCareersSpider()._find_location_tuple("<p>no blob</p>") is None


A = "https://careers.google.com/jobs/results/1-software-engineer/"
B = "https://careers.google.com/jobs/results/2-senior-software-engineer/"
C = "https://careers.google.com/jobs/results/3-staff-software-engineer/"


def test_permitted_scope_is_complete_before_first_request_is_validated() -> None:
    """The permitted scope is complete before any request is yielded.

    The verified defect: parse() grows allowed_sitemap_urls while it yields
    (sizes 1, 2, 3), so a consumer inspecting it mid-stream sees a partial
    scope. The live crawl meanwhile failed with the guard observing an empty
    set.
    """
    spider = GoogleCareersSpider()
    observed: list[tuple[str, int]] = []
    for request in spider.parse(_sitemap_response([A, B, C])):
        observed.append((request.url, len(spider.allowed_sitemap_urls)))
    assert observed == [(A, 3), (B, 3), (C, 3)]


async def test_job_redirect_target_is_permitted_after_restructure() -> None:
    """careers.google.com jobs 301 to the declared careers host; must stay legal."""
    from app.ingestion.middleware import REDIRECT_META_KEY, PolicyGuardMiddleware

    spider = GoogleCareersSpider()
    requests = list(spider.parse(_sitemap_response([A])))

    redirect_target = A.replace(
        "careers.google.com", "www.google.com/about/careers/applications"
    )
    redirected = requests[0].replace(url=redirect_target, meta={REDIRECT_META_KEY: A})

    async def stream():
        yield redirected

    passed = [
        r
        async for r in PolicyGuardMiddleware().process_spider_output(
            _sitemap_response([A]), stream(), spider
        )
    ]
    assert [r.url for r in passed] == [redirect_target]


async def test_job_redirect_target_without_in_scope_origin_raises() -> None:
    """The same target reached from a non-loc origin is not the crawl's business."""
    import pytest
    from app.ingestion.middleware import PolicyGuardMiddleware, PolicyViolation

    spider = GoogleCareersSpider()
    list(spider.parse(_sitemap_response([A])))
    target = A.replace(
        "careers.google.com", "www.google.com/about/careers/applications"
    )
    redirected = scrapy.Request(
        target, meta={"redirected_from": "https://careers.google.com/jobs/results/9-x/"}
    )

    async def stream():
        yield redirected

    with pytest.raises(PolicyViolation):
        [
            r
            async for r in PolicyGuardMiddleware().process_spider_output(
                _sitemap_response([A]), stream(), spider
            )
        ]
