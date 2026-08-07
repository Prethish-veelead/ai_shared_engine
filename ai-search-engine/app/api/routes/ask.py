"""The one endpoint every bot shares: POST /ask/{bot_id}.
Same code path for every bot — only the loaded config differs.

Now protected: the caller must be signed in (valid Entra token), and must be
allowed to use this bot (empty allowed_groups = everyone; otherwise group match).
The verified user is logged instead of "anonymous".
"""
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_pipeline
from app.bots.registry import registry
from app.core.security import ForbiddenError, User, can_access_bot
from app.db.models import ChatLog
from app.db.repositories.chat_repository import save_feedback_comment
from app.db.session import get_session
from app.rag.pipeline import RagPipeline
from app.tracking.chat_history import save_chat
from app.tracking.usage_tracker import record_chat, record_embedding

router = APIRouter(tags=["ask"])


class HistoryTurn(BaseModel):
    role: Literal["user", "assistant"]
    content: str


class AskRequest(BaseModel):
    question: str          # identity now comes from the token, not the body
    # Temporary, non-persisted conversation continuity (docs/CHAT_SESSIONS.md):
    # the browser holds the running conversation in memory and resends recent
    # turns here on every call. Text only - no tool-call/tool-result messages
    # ever cross the wire. Empty/absent = today's exact single-turn behavior.
    history: list[HistoryTurn] = Field(default_factory=list)


class Citation(BaseModel):
    index: int
    source: str
    page: int | None = None


class AskResponse(BaseModel):
    # extra="allow": a bot's configured response_fields/include_category
    # (app/bots/schema.py) are additive-only, undeclared keys - these base
    # fields never change shape for any bot, but a bot that opts in gets
    # extra top-level keys (e.g. "subject", "category") alongside them. See
    # the ask() route below, which passes them in via **result.extra_fields.
    model_config = ConfigDict(extra="allow")

    answer: str
    citations: list[Citation]
    model: str
    total_tokens: int
    cost_usd: float
    response_time_ms: int
    chat_log_id: int


@router.post("/ask/{bot_id}", response_model=AskResponse)
def ask(bot_id: str, body: AskRequest,
        user: User = Depends(get_current_user),
        pipeline: RagPipeline = Depends(get_pipeline),
        db: Session = Depends(get_session)) -> AskResponse:
    bot = registry.get(bot_id)                       # 404 if unknown/disabled

    if not can_access_bot(bot, user):                # per-bot group gate
        raise ForbiddenError(f"You do not have access to bot '{bot_id}'")

    history = [h.model_dump() for h in body.history]
    result = pipeline.answer(bot, body.question, db, history=history)

    # Record usage + cost on EVERY call, tagged with the REAL user.
    chat_cost = record_chat(
        db, bot_id=bot.id, user_id=user.id, model=result.model,
        prompt_tokens=result.prompt_tokens, completion_tokens=result.completion_tokens,
    )
    record_embedding(db, bot_id=bot.id, model=bot.models.embedding,
                     total_tokens=result.embedding_tokens)
    chat_log_id = save_chat(
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
        chat_log_id=chat_log_id,
        **result.extra_fields,
    )


class FeedbackRequest(BaseModel):
    chat_log_id: int
    feedback: Literal["like", "dislike"]
    # Dislike-only free-text reason ("Learning loop" - docs mention). Ignored
    # for "like" - a good answer doesn't need an explanation. Optional even
    # on dislike: the thumbs-down itself is never blocked on providing one.
    comment: str | None = None


@router.post("/ask/{bot_id}/feedback")
def submit_feedback(bot_id: str, body: FeedbackRequest,
                    user: User = Depends(get_current_user),
                    db: Session = Depends(get_session)) -> dict:
    """Optional: a bot consumer may never call this. It exists as a standalone
    endpoint (not baked into bot-ui) so any real frontend integrating a bot via
    its URL can wire up its own like/dislike UI against the same contract.
    """
    registry.get(bot_id)   # 404 if unknown/disabled

    chat_log = db.get(ChatLog, body.chat_log_id)
    if chat_log is None or chat_log.bot_id != bot_id:
        raise HTTPException(status_code=404, detail="chat_log_id not found for this bot")
    if chat_log.user_id != user.id:
        raise HTTPException(status_code=403, detail="You can only give feedback on your own answers")

    chat_log.feedback = body.feedback
    if body.feedback == "dislike" and body.comment and body.comment.strip():
        save_feedback_comment(db, chat_log.id, body.comment.strip())
    db.commit()
    return {"chat_log_id": chat_log.id, "feedback": chat_log.feedback}


@router.get("/bots")
def list_accessible_bots(user: User = Depends(get_current_user)):
    """Returns a list of bots the current user is allowed to access."""
    accessible_bots = []
    for bot in registry.all():
        if bot.enabled and can_access_bot(bot, user):
            accessible_bots.append({
                "id": bot.id,
                "name": bot.name,
                "route": bot.route,
                "enabled": bot.enabled,
                "sample_questions": bot.sample_questions,
            })
    return accessible_bots
