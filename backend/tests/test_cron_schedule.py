from datetime import datetime, timezone

import croniter
from app.ingestion.schedule import SCHEDULE

DAY_SECONDS = 86400


def test_cadence_is_valid_and_daily() -> None:
    base = croniter.croniter(
        SCHEDULE, start_time=datetime(2026, 1, 1, tzinfo=timezone.utc)
    )
    first = base.get_next(datetime)
    second = base.get_next(datetime)
    assert (second - first).total_seconds() == DAY_SECONDS


def test_schedule_fires_at_0617() -> None:
    base = croniter.croniter(
        SCHEDULE, start_time=datetime(2026, 1, 1, tzinfo=timezone.utc)
    )
    nxt = base.get_next(datetime)
    assert (nxt.hour, nxt.minute) == (6, 17)
