"""Read-side queries for the admin Chat History dashboard.
Filters map 1:1 to your requirements: bot / user / date / keyword.
"""
from datetime import datetime

from sqlalchemy import func, or_, select
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
        # Matches the user's email too, so typing a person's name/email finds
        # their conversations without needing the separate user_id filter
        # (which expects the opaque Entra object id, not something an admin
        # would type from memory).
        stmt = stmt.where(or_(
            ChatLog.question.ilike(like),
            ChatLog.answer.ilike(like),
            ChatLog.user_email.ilike(like),
        ))
    stmt = stmt.order_by(ChatLog.created_at.desc()).limit(limit).offset(offset)
    return list(db.scalars(stmt))


def feedback_counts_by_bot(db: Session) -> dict[str, dict[str, int]]:
    """{bot_id: {"likes": n, "dislikes": n}} across all time - feeds the
    like/dislike counts shown on the Bot Management page. Rows where feedback
    is null (nobody gave any) simply aren't counted in either bucket."""
    stmt = select(ChatLog.bot_id, ChatLog.feedback, func.count()).where(
        ChatLog.feedback.is_not(None)).group_by(ChatLog.bot_id, ChatLog.feedback)
    counts: dict[str, dict[str, int]] = {}
    for bot_id, feedback, n in db.execute(stmt):
        bucket = counts.setdefault(bot_id, {"likes": 0, "dislikes": 0})
        bucket["likes" if feedback == "like" else "dislikes"] = n
    return counts
