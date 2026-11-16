from pathlib import Path

import pytest
import scrapy
from app.ingestion.spiders.google_careers import GoogleCareersSpider
from scrapy.http import HtmlResponse, TextResponse

FIXTURES = Path(__file__).parent / "fixtures" / "google_careers"


def _fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def _job_response_for(text: str, job_id: str) -> HtmlResponse:
    """A job page response whose sitemap URL carries ``job_id``."""
    url = f"https://careers.google.com/jobs/results/{job_id}-software-engineer/"
    return HtmlResponse(url=url, body=text.encode("utf-8"), encoding="utf-8")


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


def test_job_page_without_location_yields_nothing() -> None:
    url = "https://careers.google.com/jobs/results/8-swe/"
    body = "<html><body><p>Tokyo, Japan</p></body></html>"
    spider = GoogleCareersSpider()
    assert list(spider.parse_job(_job_response(body, url))) == []


def test_spider_is_scrapy_spider() -> None:
    assert isinstance(GoogleCareersSpider(), scrapy.Spider)


# Ground truth, hand-verified against the live site. Each fixture is a trimmed
# real page: the job header (primary location) + the job's own ds:0 record
# (with its `loc=` country code).
@pytest.mark.parametrize(
    ("fixture", "job_id", "display", "city", "country"),
    [
        ("jp-tokyo.html", "80779223387513542", "Tokyo, Japan", "Tokyo", "JP"),
        ("au-sydney.html", "129819530682606278", "Sydney NSW, Australia", "Sydney", "AU"),
        ("ch-zurich.html", "78601150982431430", "Zürich, Switzerland", "Zürich", "CH"),
        ("us-newyork.html", "102729755412832966", "New York, NY, USA", "New York", "US"),
        (
            "us-mountainview.html",
            "139033052381618886",
            "Mountain View, CA, USA",
            "Mountain View",
            "US",
        ),
    ],
)
def test_extract_primary_location(
    fixture: str, job_id: str, display: str, city: str, country: str
) -> None:
    spider = GoogleCareersSpider()
    got = spider._extract_primary_location(_fixture(fixture), job_id)
    assert got is not None
    assert got.display == display
    assert got.city == city
    assert got.country == country


def test_tokyo_page_is_yielded_with_structured_location() -> None:
    spider = GoogleCareersSpider()
    result = list(spider.parse_job(_job_response_for(_fixture("jp-tokyo.html"), "80779223387513542")))
    assert len(result) == 1
    item = result[0]
    assert item["title"] == "T"
    assert item["location"] == "Tokyo, Japan"
    assert item["city"] == "Tokyo"
    assert item["country"] == "JP"
    assert item["external_job_id"] == "80779223387513542"


@pytest.mark.parametrize(
    ("fixture", "job_id"),
    [
        ("au-sydney.html", "129819530682606278"),
        ("ch-zurich.html", "78601150982431430"),
        ("us-newyork.html", "102729755412832966"),
        ("us-mountainview.html", "139033052381618886"),
    ],
)
def test_non_japan_job_is_dropped(fixture: str, job_id: str) -> None:
    spider = GoogleCareersSpider()
    assert list(spider.parse_job(_job_response_for(_fixture(fixture), job_id))) == []


def test_decoy_tokyo_tuple_on_non_japan_page_is_not_reported_as_tokyo() -> None:
    # The bug that shipped: a non-JP job page carries a stray Tokyo office tuple,
    # and a positional "first tuple" extractor labelled the job Tokyo/JP.
    job_id = "102729755412832966"
    body = (
        _fixture("us-newyork.html")
        .replace(
            "</body>",
            '<script>var offices=[["Tokyo, Japan",["Tokyo, Japan"],null,null,'
            '"Tokyo","JP"]];</script></body>',
        )
    )
    spider = GoogleCareersSpider()
    got = spider._extract_primary_location(body, job_id)
    assert got is not None
    assert got.city == "New York"
    assert got.country == "US"
    assert list(spider.parse_job(_job_response_for(body, job_id))) == []


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
