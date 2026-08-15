"""APScheduler that runs each bot's sync on its own cron (indexing.schedule).
Run this as a separate process/container from the API for isolation.
"""
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from app.bots.registry import registry
from app.core.config import get_settings
from app.core.logging import configure_logging, get_logger
from app.db.repositories.log_repository import record_event
from app.db.session import _session_factory
from app.monitoring.alerts import check_resource_thresholds
from app.workers.sync_job import (
    _library_shim,
    build_combined_sharepoint_client,
    build_sharepoint_client,
    reset_delta_tokens,
    resolve_drive_ids,
    resolve_list_ids,
    run_combined_sync,
    run_list_sync,
    run_sync,
)
from app.workers.web_sync import build_web_sharepoint_client, run_web_sync

configure_logging()
log = get_logger(__name__)


def sync_one_bot(bot_id: str, full: bool = False) -> None:
    """Run a sync for one bot - incremental (delta) by default, or a full
    re-crawl when full=True (admin portal's "Full Reindex" action resets the
    saved delta token first, so every document is re-fetched and re-chunked).
    Errors are contained so one bot's failure never crashes the scheduler or
    affects other bots.

    Writes a "sync" EventLog row on start AND on success (previously only on
    failure) - both the cron-triggered path here and the admin portal's
    manual "Sync Now"/"Full Reindex" buttons call this same function
    (app/api/routes/admin.py's sync_bot_now/reindex_bot_now), so this one
    place covers every trigger. The admin notification bell polls the
    existing GET /admin/logs endpoint for these - no new read path needed."""
    bot = registry.get_any(bot_id)   # allow disabled bots: their content can still be kept synced
    if bot.content_type == "chat":
        # No data source at all - nothing to sync, ever. Checked before any
        # event logging so a chat bot's sync trigger (cron never schedules
        # one - see main() below - but a stray manual "Sync Now" call could
        # still reach here) is a clean, silent no-op rather than a logged
        # "started" with no matching "completed"/"failed".
        log.info("Bot '%s' is content_type=chat - nothing to sync, skipping", bot_id)
        return

    label = "Reindex" if full else "Sync"
    try:
        with _session_factory()() as db:
            record_event(db, type="sync", bot_id=bot_id, message=f"{label} started")
            db.commit()
    except Exception:
        pass  # logging the start must never block the sync itself

    try:
        # web bots read their tenant from bot.web, not bot.sharepoint (which
        # they never set - see app/bots/schema.py's _valid_content_source).
        # list+library bots read tenant from bot.list_plus_library.
        if bot.content_type == "list+library":
            sp = build_combined_sharepoint_client(bot)
        elif bot.content_type == "web":
            sp = build_web_sharepoint_client(bot)
        else:
            sp = build_sharepoint_client(bot)
        with _session_factory()() as db:
            if bot.content_type == "list+library":
                # list+library always does a full re-pull for the list side
                # (same as pure list bots) and delta for the library side.
                # The "full" flag is honoured on the library side only: if
                # full=True we reset delta tokens BEFORE calling run_combined_sync,
                # which passes them to run_sync internally.
                if full:
                    # Reset only the library side's delta tokens - the same
                    # shim run_combined_sync itself uses, not a second
                    # hand-rolled copy (see sync_job._library_shim).
                    reset_delta_tokens(db, _library_shim(bot))   # type: ignore[arg-type]
                run_combined_sync(bot, db, sp=sp)
            elif bot.content_type == "list":
                # List bots always do a full re-pull (see run_list_sync) - the
                # "full" flag only matters for library bots' delta tokens.
                list_id_for = resolve_list_ids(bot, sp)
                run_list_sync(bot, db, list_id_for, sp=sp)
            elif bot.content_type == "web":
                # Web bots also always do a full re-pull per source (see
                # run_web_sync's docstring) - same reason "full" doesn't apply.
                run_web_sync(bot, db, sp=sp)
            else:
                drive_id_for = resolve_drive_ids(bot, sp)    # site_url + libraries -> ids
                if full:
                    reset_delta_tokens(db, bot)
                run_sync(bot, db, drive_id_for, sp=sp)
        log.info("%s complete for bot '%s'", label, bot_id)
        try:
            with _session_factory()() as db:
                record_event(db, type="sync", bot_id=bot_id, message=f"{label} completed successfully")
                db.commit()
        except Exception:
            pass  # logging success must never crash an otherwise-successful sync
    except Exception as exc:
        log.exception("Sync FAILED for bot '%s' (other bots unaffected)", bot_id)
        try:
            with _session_factory()() as db:
                record_event(db, type="sync", bot_id=bot_id, message=str(exc))
                db.commit()
        except Exception:
            pass   # logging the failure must never itself crash the scheduler


def _check_resources_job() -> None:
    """Scheduled job: system-wide, not per-bot - see app/monitoring/alerts.py."""
    try:
        with _session_factory()() as db:
            check_resource_thresholds(db)
    except Exception:
        log.exception("Resource threshold check failed (non-fatal, will retry next interval)")


def main() -> None:
    registry.load()
    scheduler = BlockingScheduler(timezone="UTC")
    for bot in registry.all():
        if bot.content_type == "chat":
            continue   # no data source - nothing to ever sync
        scheduler.add_job(
            sync_one_bot, CronTrigger.from_crontab(bot.indexing.schedule),
            args=[bot.id], id=f"sync-{bot.id}", replace_existing=True,
        )
        log.info("Scheduled bot '%s' at cron '%s'", bot.id, bot.indexing.schedule)

    interval_minutes = get_settings().resource_alert_check_interval_minutes
    scheduler.add_job(
        _check_resources_job, IntervalTrigger(minutes=interval_minutes),
        id="resource-threshold-check", replace_existing=True,
    )
    log.info("Scheduled resource threshold check every %d minute(s)", interval_minutes)

    log.info("Scheduler started. Waiting for cron triggers...")
    scheduler.start()


if __name__ == "__main__":
    main()
