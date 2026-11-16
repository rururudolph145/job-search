import pytest
from app.ingestion.policy import (
    GOOGLE_BUDGET,
    UnconfiguredHostError,
    budget_for,
    registrable_host,
)


def test_registrable_host_strips_to_two_labels() -> None:
    assert registrable_host("https://careers.google.com/jobs/sitemap") == "google.com"
    assert registrable_host("https://www.google.com/x") == "google.com"


def test_registrable_host_only_strips_the_www_label() -> None:
    # Only the literal "www." prefix is stripped; a host that merely starts with
    # those letters keeps its own last two labels.
    assert registrable_host("https://wwwx.google.com/x") == "google.com"
    assert registrable_host("https://jobs.example.com/") == "example.com"


def test_budget_for_known_host() -> None:
    assert budget_for("https://careers.google.com/jobs/results/1-a/") == GOOGLE_BUDGET


def test_budget_for_unknown_host_raises() -> None:
    with pytest.raises(UnconfiguredHostError):
        budget_for("https://jobs.example.com/x")


def test_google_budget_values_are_pinned() -> None:
    assert GOOGLE_BUDGET.download_delay == 2.0
    assert GOOGLE_BUDGET.concurrent_requests_per_domain == 1
    assert GOOGLE_BUDGET.autothrottle_target_concurrency == 1.0
    assert GOOGLE_BUDGET.autothrottle_max_delay == 30.0
