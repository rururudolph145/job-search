"""One-shot ingestion CLI: python -m app.ingest [--limit N]."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence

from sqlalchemy.orm import Session

from app.db.engine import make_engine
from app.ingestion.service import IngestionService
from app.ingestion.sources.base import JobSource
from app.ingestion.sources.google_careers import make_google_careers_source


def build_source() -> JobSource:
    """Seam so the CLI is testable without network access (fake it in tests)."""
    return make_google_careers_source()


def run_ingestion(limit: int | None) -> int:
    engine = make_engine()

    def session_factory() -> Session:
        return Session(engine)

    source = build_source()
    try:
        result = IngestionService(source, session_factory).run()
    except Exception as exc:
        # Distinguish a failed feed (sitemap unreachable, network down) from a
        # successful-but-empty crawl; PBI 8 tightens this further.
        print(f"ingestion failed: sitemap unreachable ({exc})")
        return 1

    print(
        f"ingestion complete: created={result.created} "
        f"seen={result.seen} skipped_no_id={result.skipped_no_id}"
    )
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Ingest jobs from permitted feeds")
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="stop after N items (useful for a smoke run)",
    )
    args = parser.parse_args(argv)
    return run_ingestion(args.limit)


if __name__ == "__main__":
    sys.exit(main())
