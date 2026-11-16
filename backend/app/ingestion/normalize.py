"""Pure string-normalization for job fields that feed the identity key.

Deliberately conservative (spec §3): NFKC + whitespace collapse for display
fields, slug-lowercasing for `source` (a key component), and empty-as-`None`
for `external_job_id` (an id of ``" "`` is not an id). No casefolding of
`title`/`company`/`location` — they no longer feed a unique key, so case is a
display concern, not an identity concern.
"""

from __future__ import annotations

import re
import unicodedata

_COUNTRY_CODE = re.compile(r"^[A-Z]{2}$")


def _collapse(value: str) -> str:
    return " ".join(value.split())


def normalize_source(source: str) -> str:
    """Lowercase and collapse a ``jobs.source`` slug."""
    return _collapse(source.lower())


def normalize_external_id(external_job_id: str) -> str | None:
    """Strip the provider id; an empty result becomes ``None``."""
    stripped = external_job_id.strip()
    return stripped or None


def normalize_title(title: str) -> str:
    """NFKC-fold and collapse whitespace in a job title."""
    return _collapse(unicodedata.normalize("NFKC", title))


def normalize_company(company: str | None) -> str | None:
    """Normalize a company display string (currently always ``None``)."""
    if company is None:
        return None
    return normalize_title(company)


def normalize_location(location: str | None) -> str | None:
    """Normalize raw location text; no structured parsing (spec §4.2)."""
    if location is None:
        return None
    return normalize_title(location)


def normalize_country(country: str | None) -> str | None:
    """Uppercase a 2-letter ISO country code; anything else becomes ``None``."""
    if country is None:
        return None
    code = country.strip().upper()
    return code if _COUNTRY_CODE.match(code) else None
