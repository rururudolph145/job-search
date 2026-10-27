"""The crawl cadence — single source of truth (§6.9).

The README's crontab line and `test_cron_schedule.py` both derive from this
value; changing the cadence means editing this constant and the README together.
"""

SCHEDULE = "17 6 * * *"  # daily at 06:17 host-local (§3)
