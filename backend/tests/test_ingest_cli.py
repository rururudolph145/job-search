from collections.abc import Iterator

import app.ingest as ingest
import pytest
from _pytest.capture import CaptureFixture
from _pytest.monkeypatch import MonkeyPatch
from app.ingestion.drafts import JobDraft
from app.models import Base, CrawlRun
from sqlalchemy import Engine, create_engine, select
from sqlalchemy.orm import Session


class FakeSource:
    name = "google_careers"
    skipped_no_id = 0

    def fetch(self) -> Iterator[JobDraft]:
        yield JobDraft("123", "SWE", None, "Tokyo", "https://x/123-software-engineer/")


class ExplodingSource:
    name = "google_careers"
    skipped_no_id = 0

    def fetch(self) -> Iterator[JobDraft]:
        raise RuntimeError("boom")
        yield  # pragma: no cover


def _patch_engine(monkeypatch: MonkeyPatch) -> Engine:
    test_engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(test_engine)
    monkeypatch.setattr(ingest, "make_engine", lambda: test_engine)
    return test_engine


def test_success_prints_counts_and_exits_zero(
    monkeypatch: MonkeyPatch, capsys: CaptureFixture[str]
) -> None:
    monkeypatch.setattr(ingest, "build_source", FakeSource)
    test_engine = _patch_engine(monkeypatch)

    exit_code = ingest.main([])
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "created=1 seen=0 skipped_no_id=0" in output
    with Session(test_engine) as s:
        (row,) = list(s.scalars(select(CrawlRun)))
    assert row.status == "succeeded"
    # Default trigger is manual.
    assert row.trigger == "manual"


def test_failure_prints_error_and_exits_one(
    monkeypatch: MonkeyPatch, capsys: CaptureFixture[str]
) -> None:
    monkeypatch.setattr(ingest, "build_source", ExplodingSource)
    _patch_engine(monkeypatch)

    exit_code = ingest.main([])
    output = capsys.readouterr().out

    assert exit_code == 1
    assert "ingestion failed: RuntimeError: boom" in output


def test_trigger_flag_reaches_run_ingestion(
    monkeypatch: MonkeyPatch, capsys: CaptureFixture[str]
) -> None:
    calls: list[dict[str, str]] = []

    def fake_run(*, trigger: str = "manual") -> int:
        calls.append({"trigger": trigger})
        return 0

    monkeypatch.setattr(ingest, "run_ingestion", fake_run)
    assert ingest.main(["--trigger", "cron"]) == 0
    assert calls == [{"trigger": "cron"}]


def test_limit_flag_is_gone() -> None:
    # argparse rejects an unknown flag with SystemExit(2); `--limit` was dead code.
    with pytest.raises(SystemExit):
        ingest.main(["--limit", "5"])
