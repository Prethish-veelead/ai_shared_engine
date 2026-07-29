"""Aggregations for the Usage + Cost dashboards. All numbers come from GROUP BY
over usage_logs / chat_logs — no extra tables needed.

usage_logs   = one row per billable AI call (chat AND embedding) -> true cost.
chat_logs    = one row per answered question -> requests, latency, active users.
"""
from datetime import datetime, timedelta

from sqlalchemy import distinct, func, select
from sqlalchemy.orm import Session

from app.db.models import ChatLog, UsageLog
from app.tracking.cost_calculator import chat_cost


def _filter(stmt, model, bot_id, start, end):
    if bot_id:
        stmt = stmt.where(model.bot_id == bot_id)
    if start:
        stmt = stmt.where(model.created_at >= start)
    if end:
        stmt = stmt.where(model.created_at <= end)
    return stmt


# ---------- cost dashboards ----------

def cost_by_bot(db: Session, bot_id=None, start=None, end=None) -> list[dict]:
    stmt = select(UsageLog.bot_id,
                  func.sum(UsageLog.total_tokens).label("tokens"),
                  func.sum(UsageLog.cost_usd).label("cost"),
                  func.count().label("requests")).group_by(UsageLog.bot_id)
    stmt = _filter(stmt, UsageLog, bot_id, start, end)
    return [dict(r._mapping) for r in db.execute(stmt)]


def cost_by_model(db: Session, bot_id=None, start=None, end=None) -> list[dict]:
    stmt = select(UsageLog.model,
                  func.sum(UsageLog.cost_usd).label("cost"),
                  func.sum(UsageLog.total_tokens).label("tokens")).group_by(UsageLog.model)
    stmt = _filter(stmt, UsageLog, bot_id, start, end)
    return [dict(r._mapping) for r in db.execute(stmt)]


def cost_by_user(db: Session, bot_id=None, start=None, end=None) -> list[dict]:
    # Only chat calls are attributable to a user; embeddings happen during
    # ingestion and have no user, so exclude them here.
    stmt = select(UsageLog.user_id,
                  func.sum(UsageLog.cost_usd).label("cost"),
                  func.sum(UsageLog.total_tokens).label("tokens"),
                  func.count().label("requests")).where(
        UsageLog.kind == "chat").group_by(UsageLog.user_id)
    stmt = _filter(stmt, UsageLog, bot_id, start, end)
    rows = [dict(r._mapping) for r in db.execute(stmt)]

    # usage_logs only has the Entra object id (see UsageLog.user_id); chat_logs
    # records the email for the same id (see ChatLog.user_email), so look it
    # up there rather than joining - a join here would multiply usage_logs
    # rows by each user's chat_logs row count and inflate the sums above.
    user_ids = [r["user_id"] for r in rows if r["user_id"]]
    emails = {}
    if user_ids:
        email_stmt = select(ChatLog.user_id, func.max(ChatLog.user_email)).where(
            ChatLog.user_id.in_(user_ids)).group_by(ChatLog.user_id)
        emails = dict(db.execute(email_stmt).all())

    for r in rows:
        r["email"] = emails.get(r["user_id"])
    return rows


def cost_summary(db: Session, bot_id=None, start=None, end=None) -> dict:
    """Total cost split into LLM (chat) vs embedding, and LLM cost further
    split into its input-token and output-token components (different rate
    per token type, per model.pricing in config/models.yaml) - a chat call's
    stored cost_usd is already prompt+completion combined, so we recompute
    each half from the stored token counts rather than storing them separately.
    """
    stmt = select(UsageLog.kind, UsageLog.model,
                  func.sum(UsageLog.prompt_tokens).label("prompt_tokens"),
                  func.sum(UsageLog.completion_tokens).label("completion_tokens"),
                  func.sum(UsageLog.cost_usd).label("cost"),
                  ).group_by(UsageLog.kind, UsageLog.model)
    stmt = _filter(stmt, UsageLog, bot_id, start, end)

    embedding_cost = 0.0
    llm_input_cost = 0.0
    llm_output_cost = 0.0
    input_tokens = 0
    output_tokens = 0
    for kind, model, prompt_tokens, completion_tokens, cost in db.execute(stmt):
        if kind == "embedding":
            embedding_cost += float(cost or 0)
        else:
            prompt_tokens = prompt_tokens or 0
            completion_tokens = completion_tokens or 0
            llm_input_cost += chat_cost(model, prompt_tokens, 0)
            llm_output_cost += chat_cost(model, 0, completion_tokens)
            input_tokens += prompt_tokens
            output_tokens += completion_tokens

    llm_cost = llm_input_cost + llm_output_cost
    return {"total_cost": round(llm_cost + embedding_cost, 6),
            "llm_cost": round(llm_cost, 6),
            "embedding_cost": round(embedding_cost, 6),
            "llm_input_cost": round(llm_input_cost, 6),
            "llm_output_cost": round(llm_output_cost, 6),
            "input_tokens": input_tokens,
            "output_tokens": output_tokens}


# ---------- usage dashboard ----------

def usage_summary(db: Session, bot_id=None, start=None, end=None) -> dict:
    # request-level metrics come from chat_logs
    c = select(
        func.count().label("total_requests"),
        func.coalesce(func.sum(ChatLog.prompt_tokens), 0).label("prompt_tokens"),
        func.coalesce(func.sum(ChatLog.completion_tokens), 0).label("completion_tokens"),
        func.coalesce(func.sum(ChatLog.total_tokens), 0).label("total_tokens"),
        func.coalesce(func.avg(ChatLog.response_time_ms), 0).label("avg_response_time_ms"),
        func.count(distinct(ChatLog.user_id)).label("active_users"),
    )
    c = _filter(c, ChatLog, bot_id, start, end)
    row = db.execute(c).one()._mapping

    # true cost (incl. embeddings) from usage_logs
    cost = cost_summary(db, bot_id, start, end)["total_cost"]

    return {
        "total_requests": row["total_requests"],
        "prompt_tokens": int(row["prompt_tokens"]),
        "completion_tokens": int(row["completion_tokens"]),
        "total_tokens": int(row["total_tokens"]),
        "estimated_cost": cost,
        "avg_response_time_ms": round(float(row["avg_response_time_ms"]), 1),
        "active_users": row["active_users"],
        # documents_indexed / index_size come from the vector store, not the DB;
        # exposed via a separate index-status endpoint (future).
        "documents_indexed": None,
        "index_size": None,
    }


def usage_trend(db: Session, bot_id=None, start=None, end=None,
                granularity: str = "day") -> list[dict]:
    """Requests / tokens / cost bucketed by day|week|month.
    Bucketing is done in Python so it works identically on SQLite and Postgres
    (avoids dialect-specific date functions).
    """
    stmt = select(UsageLog.created_at, UsageLog.total_tokens, UsageLog.cost_usd, UsageLog.kind)
    stmt = _filter(stmt, UsageLog, bot_id, start, end)
    rows = db.execute(stmt).all()

    def bucket(dt: datetime) -> str:
        if granularity == "month":
            return dt.strftime("%Y-%m")
        if granularity == "week":
            monday = dt.date() - timedelta(days=dt.weekday())
            return monday.isoformat()
        return dt.date().isoformat()   # day

    agg: dict[str, dict] = {}
    for created_at, tokens, cost, kind in rows:
        b = agg.setdefault(bucket(created_at), {"period": bucket(created_at),
                                                "requests": 0, "tokens": 0, "cost": 0.0})
        if kind == "chat":
            b["requests"] += 1        # count chat calls as requests, not embeddings
        b["tokens"] += tokens or 0
        b["cost"] += float(cost or 0)
    return [{**v, "cost": round(v["cost"], 6)} for v in sorted(agg.values(), key=lambda x: x["period"])]
