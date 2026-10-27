"""One-shot ingestion CLI: python -m app.ingest [--trigger {cron,manual}].

Exit codes: 0 success, 1 crawl failed, 2 skipped (another run holds the lock).
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence

from sqlalchemy import Engine
from sqlalchemy.orm import Session

from app.db.engine import make_engine
from app.ingestion.run import IngestRun
from app.ingestion.sources.base import JobSource
from app.ingestion.sources.google_careers import make_google_careers_source


def build_source() -> JobSource:
    """Seam so the CLI is testable without network access (fake it in tests)."""
    return make_google_careers_source()


def run_ingestion(*, trigger: str = "manual") -> int:
    engine = make_engine()

    def session_factory() -> Session:
        return Session(engine)

    outcome = IngestRun(build_source(), session_factory, trigger).run()

    if outcome.skipped_locked:
        print("ingestion skipped: another run holds the lock")
    elif outcome.error is not None:
        print(f"ingestion failed: {outcome.error}")
    elif outcome.result is not None:
        print(
            f"ingestion complete: created={outcome.result.created} "
            f"seen={outcome.result.seen} "
            f"skipped_no_id={outcome.result.skipped_no_id}"
        )
    return outcome.exit_code


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Ingest jobs from permitted feeds")
    parser.add_argument(
        "--trigger",
        choices=["cron", "manual"],
        default="manual",
        help="how this run was started (recorded in crawl_runs)",
    )
    args = parser.parse_args(argv)
    return run_ingestion(trigger=args.trigger)


if __name__ == "__main__":
    sys.exit(main())
