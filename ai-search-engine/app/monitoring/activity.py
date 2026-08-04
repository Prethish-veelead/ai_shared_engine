"""Per-bot activity for the admin Resources page - requests/tokens/cost and
each bot's %share of them, plus last-sync info.

This is explicitly a LOAD PROXY, not a per-bot resource measurement -
app/monitoring/resources.py explains why real per-bot RAM/CPU isn't a thing
on this deployment. Every consumer of this data (the /resources page) must
present it captioned as such, never as "RAM/CPU per bot".
"""
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.bots.registry import registry
from app.db.models import ChatLog, SyncState
from app.db.repositories import usage_repository as usage


def _share(value: float, total: float) -> float:
    return round(100 * value / total, 1) if total else 0.0


def activity_by_bot(db: Session, start: datetime | None, end: datetime | None) -> list[dict]:
    cost_rows = {r["bot_id"]: r for r in usage.cost_by_bot(db, None, start, end)}

    avg_rt_stmt = select(ChatLog.bot_id, func.avg(ChatLog.response_time_ms))
    if start:
        avg_rt_stmt = avg_rt_stmt.where(ChatLog.created_at >= start)
    if end:
        avg_rt_stmt = avg_rt_stmt.where(ChatLog.created_at <= end)
    avg_rt_by_bot = dict(db.execute(avg_rt_stmt.group_by(ChatLog.bot_id)).all())

    # MIN across a bot's libraries/lists, same "only as fresh as the stalest
    # one" logic as GET /admin/index-status - a bot with several sites/
    # libraries shouldn't look fully synced just because the fastest one finished.
    last_sync_at: dict[str, datetime] = {}
    last_sync_status: dict[str, str | None] = {}
    for row in db.scalars(select(SyncState)):
        if not row.last_run_at:
            continue
        current = last_sync_at.get(row.bot_id)
        if current is None or row.last_run_at < current:
            last_sync_at[row.bot_id] = row.last_run_at
            last_sync_status[row.bot_id] = row.last_status

    total_requests = sum(r["requests"] or 0 for r in cost_rows.values())
    total_tokens = sum(r["tokens"] or 0 for r in cost_rows.values())
    total_cost = sum(float(r["cost"] or 0) for r in cost_rows.values())

    result = []
    for bot in registry.all():
        row = cost_rows.get(bot.id, {"requests": 0, "tokens": 0, "cost": 0.0})
        requests = row["requests"] or 0
        tokens = row["tokens"] or 0
        cost = float(row["cost"] or 0)
        sync_at = last_sync_at.get(bot.id)
        result.append({
            "botId": bot.id, "name": bot.name,
            "requests": requests, "tokens": tokens, "cost": round(cost, 6),
            "avgResponseTimeMs": round(float(avg_rt_by_bot.get(bot.id) or 0), 1),
            "requestsSharePct": _share(requests, total_requests),
            "tokensSharePct": _share(tokens, total_tokens),
            "costSharePct": _share(cost, total_cost),
            "lastSyncAt": sync_at.isoformat() if sync_at else None,
            "lastSyncStatus": last_sync_status.get(bot.id),
        })
    return result
