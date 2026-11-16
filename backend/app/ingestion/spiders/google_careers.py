"""Scrapy spider for Google Careers software-engineering listings.

Reads the public sitemap (``/jobs/sitemap``, a permitted feed), filters URLs to
``software-engineer`` slugs, then fetches each matching detail page and yields a
plain dict. Only Japan (``country == "JP"``) pages are yielded; the caller
filters further.

Location is read from two places on the job page, both keyed to the job's own
identity (never "the first location on the page" — every page also embeds
Google's office list and related jobs, which are decoys):

* the **primary display string** is the first ``<span class="r0wTof ">`` inside
  the job header block (``<span class="pwO9Dc vo5qdf">`` … ``place`` icon),
  e.g. ``Zürich, Switzerland`` (alternatives follow in ``r0wTof p3oCrc``);
* the **country code** is the ``loc=`` parameter on the job's own ``ds:0``
  record (``data:[["<job id>", …``), e.g. ``loc=CH``. This is authoritative
  even when the country has no office tuple on the page.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

import scrapy

SITEMAP_URL = "https://careers.google.com/jobs/sitemap"

# Role slug filter — the URL slug encodes the role, so a job can be classified as
# a software-engineer opening without fetching its page.
ROLE_PATTERN = re.compile(r"software-engineer", re.IGNORECASE)

# Leading-numeric job id on the detail URL (e.g. "/jobs/results/836830...-slug/").
ID_PATTERN = re.compile(r"^(\d+)-")

# Job header block: the primary location is the first plain ``r0wTof`` span
# (no ``p3oCrc`` secondary class) after the ``place`` icon. The header renders
# once per page, so the first match is the job's own primary location.
PRIMARY_LOCATION = re.compile(
    r'<span class="pwO9Dc vo5qdf">.*?place</i><span class="r0wTof ">([^<]*)</span>',
    re.DOTALL,
)

# Country code on the job's own record: the ``loc=`` query param, escaped as
# ``loc=`` inside the JS data blob. We anchor on the job id so a decoy
# record's ``loc=`` cannot be picked up.
LOC_CODE_TEMPLATE = r'data:\[\["{job_id}".{{0,60000}}?loc\\u003d([A-Z]{{2}})'

# Display string → city. Take the first comma-separated token, then strip a
# trailing 2-3 letter state/province code glued to it ("Sydney NSW" → "Sydney").
# "New York, NY, USA" keeps "New York" (the code is a separate token).
_CITY_SPLIT = re.compile(r"\s*,")
_TRAILING_REGION = re.compile(r"\s+[A-Z]{2,3}$")


@dataclass(frozen=True, slots=True)
class PrimaryLocation:
    """The job's own primary location, as rendered on its detail page."""

    display: str
    city: str | None
    country: str


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

        url = self._job_url(response)
        external_job_id = self._extract_id(self._slug(url))

        location = self._extract_primary_location(response.text, external_job_id)
        if location is None:
            # No primary location (format drift): drop, never guess from text.
            return
        if location.country != "JP":
            # Japan-only scope: a valid non-JP job is dropped.
            return

        yield {
            "title": title,
            "location": location.display,
            "city": location.city,
            "country": location.country,
            "external_job_id": external_job_id,
            "url": url,
        }

    def _job_url(self, response: scrapy.http.Response) -> str:
        # Prefer the sitemap's result URL (passed via meta) over response.url, which
        # follows any redirect. A response not tied to a request (e.g. a synthetic
        # HtmlResponse in tests) has no meta at all, so fall back to its url.
        meta = response.request.meta if response.request else {}
        return str(meta.get("job_url") or response.url)

    def _extract_primary_location(
        self, text: str, job_id: str
    ) -> PrimaryLocation | None:
        """Return the job's own primary location, or None on format drift.

        Both signals are anchored to the job's identity: the header block (one
        per page) for the display string, and the ``loc=`` code on the job's own
        ``ds:0`` record for the country. Neither is "the first location-shaped
        string", which on these pages is a Google office or a related job.
        """
        header = PRIMARY_LOCATION.search(text)
        if header is None:
            return None
        display = header.group(1).strip()
        if not display:
            return None

        code = re.search(LOC_CODE_TEMPLATE.format(job_id=re.escape(job_id)), text)
        if code is None:
            # Country is authoritative and non-guessable; without it, drop.
            return None
        country = code.group(1)

        city = _CITY_SPLIT.split(display, maxsplit=1)[0].strip()
        city = _TRAILING_REGION.sub("", city) or None
        return PrimaryLocation(display=display, city=city, country=country)

    def _slug(self, url: Any) -> str:
        # The id regex is anchored on the slug (the final path segment), so derrive
        # the slug from the URL's path rather than the whole URL.
        return str(url).rstrip("/").rsplit("/", 1)[-1]

    def _extract_id(self, slug: str) -> str:
        match = ID_PATTERN.match(slug)
        return match.group(1) if match else ""
