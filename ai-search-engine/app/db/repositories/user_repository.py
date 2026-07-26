"""Per-user analytics for the Users dashboard, aggregated from chat_logs."""
from sqlalchemy import distinct, func, select
from sqlalchemy.orm import Session

from app.db.models import ChatLog


def _filter(stmt, bot_id, start, end):
    if bot_id:
        stmt = stmt.where(ChatLog.bot_id == bot_id)
    if start:
        stmt = stmt.where(ChatLog.created_at >= start)
    if end:
        stmt = stmt.where(ChatLog.created_at <= end)
    return stmt


def users(db: Session, bot_id=None, start=None, end=None) -> list[dict]:
    stmt = select(
        ChatLog.user_id,
        func.max(ChatLog.user_email).label("email"),
        func.count().label("questions_asked"),
        func.coalesce(func.sum(ChatLog.total_tokens), 0).label("tokens_used"),
        func.max(ChatLog.created_at).label("last_activity"),
    ).group_by(ChatLog.user_id)
    stmt = _filter(stmt, bot_id, start, end)
    out = []
    for r in db.execute(stmt):
        m = r._mapping
        out.append({"user_id": m["user_id"], "email": m["email"],
                    "questions_asked": m["questions_asked"],
                    "tokens_used": int(m["tokens_used"]),
                    "last_activity": m["last_activity"].isoformat() if m["last_activity"] else None})
    return out


def user_counts(db: Session, bot_id=None, start=None, end=None) -> dict:
    stmt = select(func.count(distinct(ChatLog.user_id)))
    stmt = _filter(stmt, bot_id, start, end)
    return {"total_users": db.execute(stmt).scalar() or 0}
