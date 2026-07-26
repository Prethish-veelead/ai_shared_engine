"""Read-side queries for the admin Chat History dashboard.
Filters map 1:1 to your requirements: bot / user / date / keyword.
"""
from datetime import datetime

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.db.models import ChatLog


def search_chats(db: Session, *, bot_id: str | None = None, user_id: str | None = None,
                 start: datetime | None = None, end: datetime | None = None,
                 keyword: str | None = None, limit: int = 100, offset: int = 0) -> list[ChatLog]:
    stmt = select(ChatLog)
    if bot_id:
        stmt = stmt.where(ChatLog.bot_id == bot_id)
    if user_id:
        stmt = stmt.where(ChatLog.user_id == user_id)
    if start:
        stmt = stmt.where(ChatLog.created_at >= start)
    if end:
        stmt = stmt.where(ChatLog.created_at <= end)
    if keyword:
        like = f"%{keyword}%"
        # Simple ILIKE. Upgrade to a tsvector GIN index for large volumes.
        stmt = stmt.where(or_(ChatLog.question.ilike(like), ChatLog.answer.ilike(like)))
    stmt = stmt.order_by(ChatLog.created_at.desc()).limit(limit).offset(offset)
    return list(db.scalars(stmt))
