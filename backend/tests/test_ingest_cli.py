from collections.abc import Iterator

import app.ingest as ingest
from _pytest.capture import CaptureFixture
from _pytest.monkeypatch import MonkeyPatch
from app.ingestion.drafts import JobDraft
from app.models import Base
from sqlalchemy import create_engine


def test_main_prints_result_and_exits_zero(
    monkeypatch: MonkeyPatch, capsys: CaptureFixture[str]
) -> None:
    class FakeSource:
        name = "google_careers"
        skipped_no_id = 0

        def fetch(self) -> Iterator[JobDraft]:
            yield JobDraft(
                "123", "SWE", None, "Tokyo", "https://x/123-software-engineer/"
            )

    monkeypatch.setattr(ingest, "build_source", FakeSource)

    # The CLI's run_ingestion calls make_engine(); point it at an in-memory SQLite
    # DB so the test never talks to the real Postgres (hermetic unit test).
    test_engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(test_engine)
    monkeypatch.setattr(ingest, "make_engine", lambda: test_engine)

    exit_code = ingest.main([])
    output = capsys.readouterr().out
    assert exit_code == 0
    assert "created=1" in output
    assert "seen=0" in output
    assert "skipped_no_id=0" in output


def test_main_returns_nonzero_on_source_error(
    monkeypatch: MonkeyPatch, capsys: CaptureFixture[str]
) -> None:
    class ExplodingSource:
        name = "boom"
        skipped_no_id = 0

        def fetch(self) -> Iterator[JobDraft]:
            raise RuntimeError("sitemap unreachable")
            yield  # pragma: no cover

    monkeypatch.setattr(ingest, "build_source", ExplodingSource)

    exit_code = ingest.main([])
    output = capsys.readouterr().out
    assert exit_code != 0
    assert "unreachable" in output


def test_main_supports_limit_flag(
    monkeypatch: MonkeyPatch, capsys: CaptureFixture[str]
) -> None:
    calls: dict[str, int | None] = {}

    def fake_run(limit: int | None) -> int:
        calls["limit"] = limit
        return 0

    monkeypatch.setattr(ingest, "run_ingestion", fake_run)
    assert ingest.main(["--limit", "5"]) == 0
    assert calls["limit"] == 5
