"""Scrapy spider for Google Careers software-engineering listings.

Reads the public sitemap (``/jobs/sitemap``, a permitted feed), filters URLs to
``software-engineer`` slugs, then fetches each matching detail page and yields a
plain dict. Location is read from the structured tuple embedded in the page:
``["<city>, <country>",["<city>, <country>"],null,null,"<city>","<CC>"]``.
Only Japan (``country == "JP"``) pages are yielded; the caller filters further.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from typing import Any

import scrapy

SITEMAP_URL = "https://careers.google.com/jobs/sitemap"

# Role slug filter — the URL slug encodes the role, so a job can be classified as
# a software-engineer opening without fetching its page.
ROLE_PATTERN = re.compile(r"software-engineer", re.IGNORECASE)

# Leading-numeric job id on the detail URL (e.g. "/jobs/results/836830...-slug/").
ID_PATTERN = re.compile(r"^(\d+)-")

# Structured location tuple in the page's embedded JS data blob. Groups: display
# (1), city (2), ISO-3166 country code (3). The display string is duplicated as
# the second element, so a naive "first match" would be ambiguous — the groups
# pin the city/country positions.
LOCATION_TUPLE = re.compile(
    r'\[\["([^"]*)",\["[^"]*"\],null,null,"([^"]*)","([A-Z]{2}|)"\]\]'
)



class GoogleCareersSpider(scrapy.Spider):
    name = "google_careers"
    start_urls = [SITEMAP_URL]

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        # Every sitemap <loc> the spider accepted. The PolicyGuardMiddleware
        # treats this set (plus the sitemap itself) as the crawl's only legal
        # scope, so a URL added here must be added *before* it is requested.
        self.allowed_sitemap_urls: set[str] = set()

    def parse(self, response: scrapy.http.Response) -> Iterator[scrapy.Request]:
        # The sitemap uses a default namespace (xmlns), so match element names by
        # local-name() rather than a bare //loc XPath.
        #
        # Collect first, then yield: Scrapy adapts this sync generator into the
        # async middleware chain, which suspends it between items. Yielding as we
        # go let PolicyGuardMiddleware validate a request before its URL was in
        # allowed_sitemap_urls. Building both fully first restores the invariant.
        # Assigned (not updated) so a re-parse cannot inherit stale entries.
        self.allowed_sitemap_urls = set()
        requests: list[scrapy.Request] = []
        for url in response.xpath(".//*[local-name()='loc']/text()").getall():
            url = str(url).strip()
            if ROLE_PATTERN.search(url):
                self.allowed_sitemap_urls.add(url)
                requests.append(
                    scrapy.Request(url, callback=self.parse_job, meta={"job_url": url})
                )
        yield from requests

    def parse_job(
        self, response: scrapy.http.Response
    ) -> Iterator[dict[str, str | None]]:
        title = (
            response.xpath("//meta[@property='og:title']/@content").get()
            or response.xpath("//title/text()").get()
            or ""
        ).strip()

        location_tuple = self._find_location_tuple(response.text)
        if location_tuple is None:
            # No structured location (format drift): drop, never guess from text.
            return
        display, city, country = location_tuple
        if country != "JP":
            # Japan-only scope: a valid tuple for another country is dropped.
            return

        url = self._job_url(response)
        external_job_id = self._extract_id(self._slug(url))

        yield {
            "title": title,
            "location": display,
            "city": city,
            "country": country,
            "external_job_id": external_job_id,
            "url": url,
        }

    def _job_url(self, response: scrapy.http.Response) -> str:
        # Prefer the sitemap's result URL (passed via meta) over response.url, which
        # follows any redirect. A response not tied to a request (e.g. a synthetic
        # HtmlResponse in tests) has no meta at all, so fall back to its url.
        meta = response.request.meta if response.request else {}
        return str(meta.get("job_url") or response.url)

    def _find_location_tuple(self, text: str) -> tuple[str, str, str] | None:
        """Return ``(display, city, country)`` from the location tuple, or None."""
        match = LOCATION_TUPLE.search(text)
        if match is None:
            return None
        display, city, country = match.group(1), match.group(2), match.group(3)
        if not city or not country:
            return None
        return display, city, country

    def _slug(self, url: Any) -> str:
        # The id regex is anchored on the slug (the final path segment), so derrive
        # the slug from the URL's path rather than the whole URL.
        return str(url).rstrip("/").rsplit("/", 1)[-1]

    def _extract_id(self, slug: str) -> str:
        match = ID_PATTERN.match(slug)
        return match.group(1) if match else ""
