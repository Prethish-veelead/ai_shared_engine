"""APScheduler that runs each bot's sync on its own cron (indexing.schedule).
Run this as a separate process/container from the API for isolation.
"""
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger

from app.bots.registry import registry
from app.core.logging import configure_logging, get_logger
from app.db.session import _session_factory
from app.workers.sync_job import (
    build_sharepoint_client,
    reset_delta_tokens,
    resolve_drive_ids,
    run_sync,
)

configure_logging()
log = get_logger(__name__)


def sync_one_bot(bot_id: str, full: bool = False) -> None:
    """Run a sync for one bot - incremental (delta) by default, or a full
    re-crawl when full=True (admin portal's "Full Reindex" action resets the
    saved delta token first, so every document is re-fetched and re-chunked).
    Errors are contained so one bot's failure never crashes the scheduler or
    affects other bots."""
    try:
        bot = registry.get_any(bot_id)   # allow disabled bots: their content can still be kept synced
        sp = build_sharepoint_client(bot)            # per-tenant credentials
        drive_id_for = resolve_drive_ids(bot, sp)    # site_url + libraries -> ids
        with _session_factory()() as db:
            if full:
                reset_delta_tokens(db, bot)
            run_sync(bot, db, drive_id_for, sp=sp)
        log.info("%s complete for bot '%s'", "Reindex" if full else "Sync", bot_id)
    except Exception as exc:
        log.exception("Sync FAILED for bot '%s' (other bots unaffected)", bot_id)
        try:
            from app.db.repositories.log_repository import record_event
            with _session_factory()() as db:
                record_event(db, type="sync", bot_id=bot_id, message=str(exc))
                db.commit()
        except Exception:
            pass   # logging the failure must never itself crash the scheduler


def main() -> None:
    registry.load()
    scheduler = BlockingScheduler(timezone="UTC")
    for bot in registry.all():
        scheduler.add_job(
            sync_one_bot, CronTrigger.from_crontab(bot.indexing.schedule),
            args=[bot.id], id=f"sync-{bot.id}", replace_existing=True,
        )
        log.info("Scheduled bot '%s' at cron '%s'", bot.id, bot.indexing.schedule)
    log.info("Scheduler started. Waiting for cron triggers...")
    scheduler.start()


if __name__ == "__main__":
    main()
