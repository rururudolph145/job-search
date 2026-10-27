"""Per-host rate budgets (§6.2). Pure module: no Scrapy import."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from urllib.parse import urlsplit


class UnconfiguredHostError(LookupError):
    """Raised when a host has no rate budget — a config bug, not a default."""


@dataclass(frozen=True, slots=True)
class RateBudget:
    """Politeness knobs for one registrable host."""

    download_delay: float
    concurrent_requests_per_domain: int
    autothrottle_target_concurrency: float
    autothrottle_max_delay: float


GOOGLE_BUDGET = RateBudget(
    download_delay=2.0,
    concurrent_requests_per_domain=1,
    autothrottle_target_concurrency=1.0,
    autothrottle_max_delay=30.0,
)

BUDGETS: Mapping[str, RateBudget] = {"google.com": GOOGLE_BUDGET}


def registrable_host(url: str) -> str:
    """Two-label suffix of the URL's host (``www.google.com`` → ``google.com``).

    Deliberately two-label, not a public-suffix-list lookup: a PSL dependency is
    not justified for one vendor today. If a multi-label suffix (e.g.
    ``co.jp``) ever appears, replace this with a PSL library — the call sites
    already key budgets by this function's result.
    """
    host = urlsplit(url).netloc.split("@")[-1].split(":")[0].lower()
    if host.startswith("www."):
        host = host.removeprefix("www.")
    labels = host.split(".")
    return ".".join(labels[-2:])


def budget_for(url: str) -> RateBudget:
    """Look up the host's budget; unknown hosts raise ``UnconfiguredHostError``."""
    host = registrable_host(url)
    try:
        return BUDGETS[host]
    except KeyError:
        raise UnconfiguredHostError(
            f"no rate budget configured for {host!r} (from {url!r})"
        ) from None
