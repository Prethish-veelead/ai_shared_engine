"""Periodic resource-threshold alerting for the admin notification bell.

Checks system RAM/disk (app/monitoring/resources.get_resources()) against a
configurable threshold and writes an EventLog row (type="resource") when
crossed, so it shows up in the same feed as sync/error events - the admin
portal's bell polls the existing GET /admin/logs endpoint, nothing new to
read on the frontend.

Debounced: won't write a second alert for the same metric within
`resource_alert_debounce_minutes` of the last one, so staying above the
threshold for hours doesn't spam a new row every check interval. This is a
system-wide check (RAM/disk are shared across every bot, same as
app/monitoring/resources.py's own design), so it runs once per interval,
not once per bot.
"""
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.logging import get_logger
from app.db.models import EventLog
from app.db.repositories.log_repository import record_event
from app.monitoring.resources import get_resources

log = get_logger(__name__)

RESOURCE_EVENT_TYPE = "resource"


def _recently_alerted(db: Session, message_prefix: str, within_minutes: int) -> bool:
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=within_minutes)
    stmt = (
        select(EventLog.id)
        .where(EventLog.type == RESOURCE_EVENT_TYPE,
               EventLog.message.like(f"{message_prefix}%"),
               EventLog.created_at >= cutoff)
        .limit(1)
    )
    return db.execute(stmt).first() is not None


def check_resource_thresholds(db: Session) -> None:
    """Called periodically from the worker's scheduler (see
    app/workers/sync_scheduler.py). Never raises - a failed check must not
    take down the scheduler any more than a failed bot sync does."""
    settings = get_settings()
    threshold = settings.resource_alert_threshold_pct
    debounce_minutes = settings.resource_alert_debounce_minutes

    try:
        resources = get_resources()
    except Exception:
        log.exception("Resource threshold check: could not read system resources")
        return

    for label, pct in [
        ("Memory usage", resources["memory"]["pct"]),
        ("Disk usage", resources["disk"]["pct"]),
    ]:
        if pct < threshold:
            continue
        if _recently_alerted(db, label, debounce_minutes):
            continue
        record_event(db, type=RESOURCE_EVENT_TYPE,
                     message=f"{label} at {pct:.1f}% (threshold {threshold:.0f}%)")
        db.commit()
        log.warning("%s crossed alert threshold: %.1f%% >= %.0f%%", label, pct, threshold)
