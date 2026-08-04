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
        # A date-only `end` (e.g. "2026-08-04") parses as that day's
        # midnight, and every caller filters with created_at <= end - which
        # would silently exclude every row from that entire day. Bump a
        # midnight end to the last instant of that day so "custom range
        # Aug 1-4" actually includes all of Aug 4; an end that already
        # carries a real time-of-day is left untouched.
        if end is not None and end.time() == time.min:
            end = datetime.combine(end.date(), time.max, tzinfo=end.tzinfo)
        return start, end
    return None, None   # all time
