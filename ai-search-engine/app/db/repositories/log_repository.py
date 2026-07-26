"""Write + read event logs for the admin Logs & Monitoring dashboard."""
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import EventLog


def record_event(db: Session, *, type: str, message: str, bot_id: str | None = None) -> None:
    """Persist one event. Call from error handlers / sync failures / etc."""
    db.add(EventLog(type=type, message=message[:4000], bot_id=bot_id))


def search_events(db: Session, *, type: str | None = None, bot_id: str | None = None,
                  start: datetime | None = None, end: datetime | None = None,
                  limit: int = 200) -> list[dict]:
    stmt = select(EventLog)
    if type:
        stmt = stmt.where(EventLog.type == type)
    if bot_id:
        stmt = stmt.where(EventLog.bot_id == bot_id)
    if start:
        stmt = stmt.where(EventLog.created_at >= start)
    if end:
        stmt = stmt.where(EventLog.created_at <= end)
    stmt = stmt.order_by(EventLog.created_at.desc()).limit(limit)
    return [{"id": e.id, "type": e.type, "bot_id": e.bot_id, "message": e.message,
             "timestamp": e.created_at.isoformat()} for e in db.scalars(stmt)]
