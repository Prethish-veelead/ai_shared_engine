"""Admin analytics assistant: answers natural-language questions about bot
usage/cost/config. It picks one of a small FIXED set of tools - each one a
direct call to an existing usage_repository query or the bot registry - then
phrases the result. Deliberately not a text-to-SQL bot: the LLM only ever
selects and parametrizes a known-safe read query, it never generates SQL or
touches the database directly.
"""
import json
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.bots.registry import registry
from app.core.exceptions import UpstreamError
from app.db.repositories import usage_repository as usage
from app.llm.base import LLMClient
from app.tracking.usage_tracker import record_chat

ASSISTANT_BOT_ID = "admin✨"
ASSISTANT_MODEL = "gpt-4o-mini"

TOOLS = ["usage_by_bot", "top_users_by_tokens", "cost_by_model", "list_bots"]

_CLASSIFY_SYSTEM = f"""You are a router for an internal admin analytics assistant. Given an admin's question, choose exactly ONE tool and respond with ONLY a JSON object - no other text, no markdown fences.

Tools:
- "usage_by_bot": requests/tokens/cost broken down per bot
- "top_users_by_tokens": which users consumed the most tokens
- "cost_by_model": cost/tokens broken down per AI model
- "list_bots": configured bots (name, route, models, SharePoint site)

Respond with exactly this shape:
{{"tool": "<one of {TOOLS}>", "period_days": <integer days to look back, or null for all-time>}}

Examples:
"how many requests did hr and it bot get?" -> {{"tool": "usage_by_bot", "period_days": null}}
"in the last 7 days which person used more tokens?" -> {{"tool": "top_users_by_tokens", "period_days": 7}}
"which model cost highest?" -> {{"tool": "cost_by_model", "period_days": null}}
"show me all bot info" -> {{"tool": "list_bots", "period_days": null}}
"""


def _round_costs(rows: list[dict]) -> list[dict]:
    # cost_by_* returns a raw SQL SUM() float (e.g. 0.04770885000000002) - the
    # dashboards round this at render time, but this assistant hands rows
    # straight to the LLM as text, so round here or that noise ends up quoted
    # verbatim in the answer.
    for r in rows:
        if r.get("cost") is not None:
            r["cost"] = round(r["cost"], 6)
    return rows


def _run_tool(db: Session, tool: str, period_days: int | None) -> dict:
    start = datetime.now(timezone.utc) - timedelta(days=period_days) if period_days else None

    if tool == "usage_by_bot":
        return {"bots": _round_costs(usage.cost_by_bot(db, start=start))}

    if tool == "top_users_by_tokens":
        rows = _round_costs(usage.cost_by_user(db, start=start))
        rows.sort(key=lambda r: r["tokens"] or 0, reverse=True)
        return {"users": rows[:10]}

    if tool == "cost_by_model":
        rows = _round_costs(usage.cost_by_model(db, start=start))
        rows.sort(key=lambda r: r["cost"] or 0, reverse=True)
        return {"models": rows}

    if tool == "list_bots":
        # sharepoint is null for content_type=web bots (they use `web`
        # instead - see app/bots/schema.py's _valid_content_source).
        return {"bots": [{
            "id": b.id, "name": b.name, "route": b.route, "enabled": b.enabled,
            "llm_model": b.models.llm, "embedding_model": b.models.embedding,
            "sharepoint_sites": [s.site_url for s in b.sharepoint.sites] if b.sharepoint else [],
            "web_source_url": b.web.site_url if b.web else None,
        } for b in registry.all()]}

    raise ValueError(f"Unknown tool '{tool}'")


def ask_admin_assistant(db: Session, question: str, llm: LLMClient, user_id: str | None) -> str:
    # Step 1: classify - which tool, and what date range.
    classify = llm.chat(system=_CLASSIFY_SYSTEM, user=question, model=ASSISTANT_MODEL, temperature=0.0)

    try:
        choice = json.loads(classify.text)
        tool = choice["tool"]
        period_days = choice.get("period_days")
    except (json.JSONDecodeError, KeyError, TypeError) as exc:
        raise UpstreamError(f"Could not understand which report to run: {exc}") from exc

    if tool not in TOOLS:
        raise UpstreamError(f"Assistant picked an unrecognized tool: {tool}")

    # Step 2: run the actual (fixed, parameterized) query - never LLM-generated SQL.
    data = _run_tool(db, tool, period_days)

    # Step 3: phrase a natural-language answer from the real data returned
    # above - same "answer only from the given context" pattern the RAG bots
    # use, so this can't invent numbers that aren't in `data`.
    answer_system = (
        "You are an internal admin analytics assistant. Answer the admin's "
        "question using ONLY the JSON data below. Be concise, cite real "
        "numbers from the data, and name specific bots/users/models where "
        "relevant. If the data is empty, say so plainly rather than guessing.\n\n"
        "Copy identifiers - model names, bot ids, emails - EXACTLY as they "
        "appear in the data, character for character. Never shorten, "
        "normalize, or 'clean up' a name (e.g. the model 'gpt-4o' must stay "
        "'gpt-4o' in your answer, never 'gpt-4' or 'GPT-4').\n\n"
        f"Data:\n{json.dumps(data, default=str)}"
    )
    final = llm.chat(system=answer_system, user=question, model=ASSISTANT_MODEL, temperature=0.0)

    record_chat(
        db, bot_id=ASSISTANT_BOT_ID, user_id=user_id, model=ASSISTANT_MODEL,
        prompt_tokens=classify.prompt_tokens + final.prompt_tokens,
        completion_tokens=classify.completion_tokens + final.completion_tokens,
    )
    db.commit()

    return final.text
