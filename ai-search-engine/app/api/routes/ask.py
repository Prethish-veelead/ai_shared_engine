"""The one endpoint every bot shares: POST /ask/{bot_id}.
Same code path for every bot — only the loaded config differs.

Now protected: the caller must be signed in (valid Entra token), and must be
allowed to use this bot (empty allowed_groups = everyone; otherwise group match).
The verified user is logged instead of "anonymous".
"""
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_pipeline
from app.bots.registry import registry
from app.core.security import ForbiddenError, User, can_access_bot
from app.db.session import get_session
from app.rag.pipeline import RagPipeline
from app.tracking.chat_history import save_chat
from app.tracking.usage_tracker import record_chat, record_embedding

router = APIRouter(tags=["ask"])


class AskRequest(BaseModel):
    question: str          # identity now comes from the token, not the body


class Citation(BaseModel):
    index: int
    source: str
    page: int | None = None


class AskResponse(BaseModel):
    answer: str
    citations: list[Citation]
    model: str
    total_tokens: int
    cost_usd: float
    response_time_ms: int


@router.post("/ask/{bot_id}", response_model=AskResponse)
def ask(bot_id: str, body: AskRequest,
        user: User = Depends(get_current_user),
        pipeline: RagPipeline = Depends(get_pipeline),
        db: Session = Depends(get_session)) -> AskResponse:
    bot = registry.get(bot_id)                       # 404 if unknown/disabled

    if not can_access_bot(bot, user):                # per-bot group gate
        raise ForbiddenError(f"You do not have access to bot '{bot_id}'")

    result = pipeline.answer(bot, body.question)

    # Record usage + cost on EVERY call, tagged with the REAL user.
    chat_cost = record_chat(
        db, bot_id=bot.id, user_id=user.id, model=result.model,
        prompt_tokens=result.prompt_tokens, completion_tokens=result.completion_tokens,
    )
    record_embedding(db, bot_id=bot.id, model=bot.models.embedding,
                     total_tokens=result.embedding_tokens)
    save_chat(
        db, bot_id=bot.id, user_id=user.id, user_email=user.email,
        question=body.question, answer=result.answer, citations=result.citations,
        model=result.model, prompt_tokens=result.prompt_tokens,
        completion_tokens=result.completion_tokens, cost_usd=chat_cost,
        response_time_ms=result.response_time_ms,
    )
    db.commit()

    return AskResponse(
        answer=result.answer,
        citations=[Citation(**c) for c in result.citations],
        model=result.model,
        total_tokens=result.prompt_tokens + result.completion_tokens,
        cost_usd=round(chat_cost, 6),
        response_time_ms=result.response_time_ms,
    )
