"""Minimal spider: discover Software Engineering jobs in Japan from Google Careers.

Compliance note: this reads the public sitemap at careers.google.com/jobs/sitemap
(a permitted feed), then follows individual job-detail URLs. Note those detail URLs
redirect to www.google.com/about/careers/applications/jobs/results/..., a path
under Google's robots.txt Disallow prefix — see experiment_scrapy/README.md. The
paginated search/results listing is never fetched.
"""

from __future__ import annotations

import re

import scrapy

SITEMAP_URL = "https://careers.google.com/jobs/sitemap"

# Role slug filter — the URL slug encodes the role, so we can classify a job as a
# software-engineer opening without fetching its page.
ROLE_PATTERN = re.compile(r"software-engineer", re.IGNORECASE)

# Best-effort location signals. The job page server-renders location text (e.g.
# "Tokyo", "Japan") but exposes no structured field, so we match known terms.
# Order matters: match city-level first for a more specific answer.
JAPAN_LOCATIONS = [
    "Tokyo",
    "Shinjuku",
    "Minato",
    "Chiyoda",
    "Shibuya",
    "Shibaura",
    "Roppongi",
    "Meguro",
    "Setagaya",
    "Osaka",
    "Kyoto",
    "Yokohama",
    "Nagoya",
    "Sapporo",
    "Fukuoka",
    "Sendai",
]


class GoogleCareersSpider(scrapy.Spider):
    name = "google_careers_sw_japan"
    start_urls = [SITEMAP_URL]

    def parse(self, response):
        # The sitemap uses a default namespace (xmlns), so match element names by
        # local-name() rather than a bare //loc XPath.
        for url in response.xpath(".//*[local-name()='loc']/text()").getall():
            url = url.strip()
            if ROLE_PATTERN.search(url):
                yield scrapy.Request(
                    url, callback=self.parse_job, meta={"job_url": url}
                )

    def parse_job(self, response) -> dict[str, str | None]:
        title = (
            response.xpath("//meta[@property='og:title']/@content").get()
            or response.xpath("//title/text()").get()
            or ""
        ).strip()

        body_text = response.xpath("//body//text()").getall()
        location = self._find_location(" ".join(body_text))

        return {
            "title": title,
            "location": location,
            "url": response.meta.get("job_url", response.url),
        }

    def _find_location(self, text: str) -> str | None:
        """Return the first matched Japan location string, or None."""
        for loc in JAPAN_LOCATIONS:
            if loc.lower() in text.lower():
                return loc
        return None
