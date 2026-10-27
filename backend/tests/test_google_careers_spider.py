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


def test_job_page_tokyo_sw_yields_full_dict() -> None:
    url = (
        "https://careers.google.com/jobs/results/"
        "83683003800134342-software-engineering-manager/"
    )
    body = (
        '<html><head><meta property="og:title" content="SWE Manager"/></head>'
        "<body><p>Tokyo, Japan</p></body></html>"
    )
    spider = GoogleCareersSpider()
    result = list(spider.parse_job(_job_response(body, url)))
    assert len(result) == 1
    item = result[0]
    assert item["title"] == "SWE Manager"
    assert item["location"] == "Tokyo"
    assert item["external_job_id"] == "83683003800134342"
    assert item["url"] == url


def test_job_page_no_tokyo_term_yields_nothing() -> None:
    url = "https://careers.google.com/jobs/results/999-software-engineer/"
    body = "<html><head><title>T</title></head><body><p>Osaka, Japan</p></body></html>"
    spider = GoogleCareersSpider()
    assert list(spider.parse_job(_job_response(body, url))) == []


def test_job_page_no_leading_id_yields_empty_id() -> None:
    url = "https://careers.google.com/jobs/results/software-engineer/"
    body = (
        "<html><head><title>SWE</title></head><body><p>Remote, Tokyo</p></body></html>"
    )
    spider = GoogleCareersSpider()
    result = list(spider.parse_job(_job_response(body, url)))
    assert len(result) == 1
    assert result[0]["external_job_id"] == ""


def test_find_location_returns_first_tokyo_term() -> None:
    spider = GoogleCareersSpider()
    assert spider._find_location("work in Shibuya near Minato") == "Shibuya"
    assert spider._find_location("no match here") is None


def test_spider_is_scrapy_spider() -> None:
    assert isinstance(GoogleCareersSpider(), scrapy.Spider)
