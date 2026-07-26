"""Writes usage_logs rows. Call this after EVERY AI call."""
from sqlalchemy.orm import Session

from app.db.models import UsageLog
from app.tracking.cost_calculator import chat_cost, embedding_cost


def record_chat(db: Session, *, bot_id: str, user_id: str | None, model: str,
                prompt_tokens: int, completion_tokens: int) -> float:
    cost = chat_cost(model, prompt_tokens, completion_tokens)
    db.add(UsageLog(
        bot_id=bot_id, user_id=user_id, kind="chat", model=model,
        prompt_tokens=prompt_tokens, completion_tokens=completion_tokens,
        total_tokens=prompt_tokens + completion_tokens, cost_usd=cost,
    ))
    return cost


def record_embedding(db: Session, *, bot_id: str, model: str, total_tokens: int) -> float:
    cost = embedding_cost(model, total_tokens)
    db.add(UsageLog(
        bot_id=bot_id, user_id=None, kind="embedding", model=model,
        total_tokens=total_tokens, cost_usd=cost,
    ))
    return cost
