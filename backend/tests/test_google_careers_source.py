from app.ingestion.sources.google_careers import GoogleCareersSource


def test_source_converts_yielded_dicts_to_drafts() -> None:
    canned: list[dict[str, str | None]] = [
        {
            "title": "SWE",
            "location": "Tokyo",
            "external_job_id": "123",
            "url": "https://careers.google.com/jobs/results/123-software-engineer/",
        },
        {
            "title": "SWE II",
            "location": "Shibuya",
            "external_job_id": "456",
            "url": "https://careers.google.com/jobs/results/456-software-engineer/",
        },
    ]

    class FakeSource(GoogleCareersSource):
        def _run_crawl(self, spider: object) -> list[dict[str, str | None]]:
            return canned

    drafts = list(FakeSource().fetch())
    assert [d.external_job_id for d in drafts] == ["123", "456"]
    assert drafts[0].url == canned[0]["url"]
    assert drafts[0].company is None


def test_source_drops_and_counts_skipped_no_id() -> None:
    canned: list[dict[str, str | None]] = [
        {
            "title": "No id",
            "location": "Tokyo",
            "external_job_id": "",
            "url": "https://careers.google.com/jobs/results/software-engineer/",
        },
        {
            "title": "With id",
            "location": "Tokyo",
            "external_job_id": "789",
            "url": "https://careers.google.com/jobs/results/789-software-engineer/",
        },
    ]

    class FakeSource(GoogleCareersSource):
        def _run_crawl(self, spider: object) -> list[dict[str, str | None]]:
            return canned

    source = FakeSource()
    drafts = list(source.fetch())
    assert [d.external_job_id for d in drafts] == ["789"]
    assert source.skipped_no_id == 1


def test_source_name_is_google_careers() -> None:
    assert GoogleCareersSource().name == "google_careers"


def test_source_raises_fetch_error_when_crawl_fails() -> None:
    from app.ingestion.sources.google_careers import FetchError

    class FailingSource(GoogleCareersSource):
        def _run_crawl(self, spider: object) -> list[dict[str, str | None]]:
            raise FetchError("sitemap unreachable")

    import pytest

    with pytest.raises(FetchError):
        list(FailingSource().fetch())


def test_source_normalizes_draft_fields() -> None:
    canned: list[dict[str, str | None]] = [
        {
            "title": " Ｆull Stack   Engineer ",
            "location": "  Tokyo\tMetro ",
            "company": None,
            "external_job_id": " 123 ",
            "url": "https://careers.google.com/jobs/results/123-full-stack/",
        },
        {
            "title": "Data   Scientist",
            "location": None,
            "external_job_id": "   ",
            "url": "https://careers.google.com/jobs/results/data-scientist/",
        },
    ]

    class FakeSource(GoogleCareersSource):
        def _run_crawl(self, spider: object) -> list[dict[str, str | None]]:
            return canned

    source = FakeSource()
    drafts = list(source.fetch())
    assert len(drafts) == 1
    assert drafts[0].external_job_id == "123"
    assert drafts[0].title == "Full Stack Engineer"
    assert drafts[0].location == "Tokyo Metro"
    assert drafts[0].company is None
    # Whitespace-only id is not an id: dropped and counted, never `""` or `" "`.
    assert source.skipped_no_id == 1
