"""Scrapy spider for Google Careers software-engineering listings.

Reads the public sitemap (``/jobs/sitemap``, a permitted feed), filters URLs to
``software-engineer`` slugs, then fetches each matching detail page and yields a
plain dict. Location is narrowed to Tokyo-metro terms; pages matching none yield
nothing (the caller filters them out).
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

# Best-effort location signals, narrowed to Tokyo-metro (spec §2). Order matters:
# match city-level first for a more specific answer.
TOKYO_TERMS = [
    "Tokyo",
    "Shinjuku",
    "Minato",
    "Chiyoda",
    "Shibuya",
    "Shibaura",
    "Roppongi",
    "Meguro",
    "Setagaya",
]


class GoogleCareersSpider(scrapy.Spider):
    name = "google_careers"
    start_urls = [SITEMAP_URL]

    def parse(self, response: scrapy.http.Response) -> Iterator[scrapy.Request]:
        # The sitemap uses a default namespace (xmlns), so match element names by
        # local-name() rather than a bare //loc XPath.
        for url in response.xpath(".//*[local-name()='loc']/text()").getall():
            url = str(url).strip()
            if ROLE_PATTERN.search(url):
                yield scrapy.Request(
                    url, callback=self.parse_job, meta={"job_url": url}
                )

    def parse_job(
        self, response: scrapy.http.Response
    ) -> Iterator[dict[str, str | None]]:
        title = (
            response.xpath("//meta[@property='og:title']/@content").get()
            or response.xpath("//title/text()").get()
            or ""
        ).strip()

        body_text = " ".join(response.xpath("//body//text()").getall())
        location = self._find_location(body_text)
        if location is None:
            # Tokyo-only filter (spec §2): a page matching no Tokyo term yields
            # nothing — it is filtered out, not stored with a null location.
            return

        url = self._job_url(response)
        external_job_id = self._extract_id(self._slug(url))

        yield {
            "title": title,
            "location": location,
            "external_job_id": external_job_id,
            "url": url,
        }

    def _job_url(self, response: scrapy.http.Response) -> str:
        # Prefer the sitemap's result URL (passed via meta) over response.url, which
        # follows any redirect. A response not tied to a request (e.g. a synthetic
        # HtmlResponse in tests) has no meta at all, so fall back to its url.
        meta = response.request.meta if response.request else {}
        return str(meta.get("job_url") or response.url)

    def _find_location(self, text: str) -> str | None:
        """Return the Tokyo term that appears first in the text, or ``None``."""
        lowered = text.lower()
        best: tuple[int, str] | None = None
        for term in TOKYO_TERMS:
            idx = lowered.find(term.lower())
            if idx == -1:
                continue
            if best is None or idx < best[0]:
                best = (idx, term)
        return best[1] if best is not None else None

    def _slug(self, url: Any) -> str:
        # The id regex is anchored on the slug (the final path segment), so derrive
        # the slug from the URL's path rather than the whole URL.
        return str(url).rstrip("/").rsplit("/", 1)[-1]

    def _extract_id(self, slug: str) -> str:
        match = ID_PATTERN.match(slug)
        return match.group(1) if match else ""
