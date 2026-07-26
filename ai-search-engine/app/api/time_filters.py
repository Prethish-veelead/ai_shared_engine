"""Maps the dashboard time presets to concrete (start, end) datetime ranges.
Used by every usage/cost/user endpoint so filters behave identically.
"""
from datetime import datetime, time, timedelta, timezone

Range = tuple[datetime | None, datetime | None]


def resolve_range(period: str | None,
                  start: datetime | None = None,
                  end: datetime | None = None) -> Range:
    """period: today | yesterday | last_7_days | last_30_days | this_month |
    custom | None (all time). For 'custom', pass start/end explicitly.
    """
    now = datetime.now(timezone.utc)
    today0 = datetime.combine(now.date(), time.min, tzinfo=timezone.utc)

    if period == "today":
        return today0, now
    if period == "yesterday":
        return today0 - timedelta(days=1), today0
    if period == "last_7_days":
        return now - timedelta(days=7), now
    if period == "last_30_days":
        return now - timedelta(days=30), now
    if period == "this_month":
        return today0.replace(day=1), now
    if period == "custom":
        return start, end
    return None, None   # all time
