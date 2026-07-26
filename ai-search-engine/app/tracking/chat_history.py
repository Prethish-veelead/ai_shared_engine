"""Persists one ChatLog row per answered question."""
import json

from sqlalchemy.orm import Session

from app.db.models import ChatLog


def save_chat(db: Session, *, bot_id: str, user_id: str, user_email: str | None,
              question: str, answer: str, citations: list[dict], model: str,
              prompt_tokens: int, completion_tokens: int, cost_usd: float,
              response_time_ms: int) -> None:
    db.add(ChatLog(
        bot_id=bot_id, user_id=user_id, user_email=user_email,
        question=question, answer=answer, citations=json.dumps(citations),
        model=model, prompt_tokens=prompt_tokens, completion_tokens=completion_tokens,
        total_tokens=prompt_tokens + completion_tokens, cost_usd=cost_usd,
        response_time_ms=response_time_ms,
    ))
