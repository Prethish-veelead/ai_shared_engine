"""Admin API — the endpoints the admin portal (Antigravity) calls.
Shapes match docs/API_CONTRACT.md. Add Entra ID admin-role checks here before
exposing publicly (see core/security.py).
"""
from datetime import datetime

from fastapi import APIRouter, BackgroundTasks, Depends, Query

from app.api.deps import get_vector_store, require_admin
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.time_filters import resolve_range
from app.bots import config_writer
from app.bots.registry import registry
from app.bots.schema import BotConfig
from app.core.config import get_settings
from app.core.exceptions import ConfigError, UpstreamError
from app.db.models import SyncState
from app.db.repositories import usage_repository as usage
from app.db.repositories import user_repository as users_repo
from app.db.repositories.chat_repository import search_chats
from app.db.repositories.log_repository import search_events
from app.db.session import get_session
from app.workers.sync_scheduler import sync_one_bot

router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(require_admin)])


# ---------- bot management (CRUD) ----------

@router.get("/bots")
def list_bots() -> list[dict]:
    # Field names are flat + camelCase to match the admin-portal's Bot type
    # directly (src/lib/api.ts) - no translation layer needed on the frontend.
    # Previously this only returned id/name/route/enabled, which meant the
    # edit form had nothing to pre-fill with and silently reset every other
    # field to a default on save.
    return [{
        "id": b.id, "name": b.name, "route": b.route, "enabled": b.enabled,
        "sharepointSite": b.sharepoint.site_url,
        "sharepointLibraries": b.sharepoint.libraries,
        "qdrantCollection": b.vectorstore.collection,
        "llmModel": b.models.llm,
        "embeddingModel": b.models.embedding,
        "indexingSchedule": b.indexing.schedule,
        "systemPrompt": b.prompt.system,
        "access": {"allowed_groups": b.access.allowed_groups},
    } for b in registry.all()]


@router.get("/index-status")
def index_status(bot_id: str | None = None, db: Session = Depends(get_session)) -> list[dict]:
    """Live document/chunk counts per bot, read directly from the vector
    store (not persisted in Postgres by design - see usage_repository.
    usage_summary(), which leaves documents_indexed/index_size null for the
    same reason: this data lives in Qdrant, not the DB)."""
    store = get_vector_store()
    bots = [b for b in registry.all() if not bot_id or b.id == bot_id]

    states_by_bot: dict[str, list[SyncState]] = {}
    for s in db.scalars(select(SyncState)):
        states_by_bot.setdefault(s.bot_id, []).append(s)

    result = []
    for bot in bots:
        stats = store.index_stats(bot.vectorstore.collection)
        states = states_by_bot.get(bot.id, [])
        last_run = max((s.last_run_at for s in states if s.last_run_at), default=None)
        result.append({
            "bot_id": bot.id,
            "documents_indexed": stats["documents"],
            "chunks_indexed": stats["chunks"],
            "last_sync_at": last_run.isoformat() if last_run else None,
        })
    return result


@router.post("/bots/reload")
def reload_bots() -> dict:
    registry.reload()
    return {"reloaded": len(registry.all())}


@router.get("/models")
def list_available_models() -> dict:
    """Live deployments on this Azure OpenAI resource, split into llm vs
    embedding by base model name. Powers the Bot Management form's dropdowns
    so they can only offer deployments that actually exist (previously
    hardcoded, so the form could reference a deployment name the resource
    doesn't have)."""
    import requests

    s = get_settings()
    if not (s.azure_openai_endpoint and s.azure_openai_api_key):
        raise ConfigError("Azure OpenAI endpoint/key not configured (.env)")

    # The deployments-LIST operation only exists on older data-plane api
    # versions (confirmed: 2022-12-01 works, 2024-xx does not - unrelated to
    # AZURE_OPENAI_API_VERSION, which is for chat/embedding calls elsewhere).
    url = f"{s.azure_openai_endpoint.rstrip('/')}/openai/deployments?api-version=2022-12-01"
    try:
        resp = requests.get(url, headers={"api-key": s.azure_openai_api_key}, timeout=30)
        resp.raise_for_status()
    except Exception as exc:
        raise UpstreamError(f"Failed to list Azure OpenAI deployments: {exc}") from exc

    llm, embedding = [], []
    for d in resp.json().get("data", []):
        name = d.get("id")
        model = (d.get("model") or "").lower()
        if not name:
            continue
        (embedding if "embedding" in model else llm).append(name)

    # Azure OpenAI only lists ITS OWN deployments - the locally-run embedding
    # model (when embedding_backend=local) isn't an Azure deployment, so it
    # would never appear here otherwise, and the form couldn't offer the
    # model that's actually configured on every bot. Use the bare model name
    # (strip the "BAAI/" org prefix) - that's what bot YAMLs and usage_logs
    # store; LOCAL_EMBEDDING_MODEL's full HF id is only needed to load it.
    if s.embedding_backend == "local":
        local_name = s.local_embedding_model.split("/")[-1]
        if local_name not in embedding:
            embedding.append(local_name)

    return {"llm": sorted(llm), "embedding": sorted(embedding)}


@router.get("/sharepoint/libraries")
def sharepoint_libraries(site_url: str, tenant: str = "veelead-development") -> list[str]:
    """List the real document libraries at a SharePoint site - powers the Bot
    Management form's library picker so admins choose from what actually
    exists instead of typing a name that might not match (this is exactly
    the bug that silently broke the hr bot's sync earlier: the configured
    library name didn't match the site's real library name)."""
    from app.ingestion.sharepoint_client import SharePointClient
    from app.ingestion.tenant_resolver import resolve_tenant

    creds = resolve_tenant(tenant)
    client = SharePointClient(creds.tenant_id, creds.client_id, creds.client_secret)
    try:
        site_id = client.resolve_site(site_url)
        drives = client.resolve_drives(site_id)
    except Exception as exc:
        raise UpstreamError(f"Failed to resolve SharePoint site/libraries: {exc}") from exc
    return sorted(drives.keys())


@router.post("/bots")
def create_bot(cfg: BotConfig) -> dict:
    config_writer.create_bot(cfg)
    return {"created": cfg.id}


@router.put("/bots/{bot_id}")
def update_bot(bot_id: str, cfg: BotConfig) -> dict:
    config_writer.update_bot(bot_id, cfg)
    return {"updated": bot_id}


@router.patch("/bots/{bot_id}")
def toggle_bot(bot_id: str, enabled: bool) -> dict:
    config_writer.set_enabled(bot_id, enabled)
    return {"bot_id": bot_id, "enabled": enabled}


@router.delete("/bots/{bot_id}")
def delete_bot(bot_id: str, db: Session = Depends(get_session)) -> dict:
    # Also drops the bot's Qdrant collection and sync_state rows - see
    # config_writer.delete_bot() for what's intentionally left alone (cost/
    # audit history in chat_logs/usage_logs).
    config_writer.delete_bot(bot_id, vector_store=get_vector_store(), db=db)
    return {"deleted": bot_id}


@router.post("/bots/{bot_id}/sync")
def sync_bot_now(bot_id: str, background_tasks: BackgroundTasks) -> dict:
    """Trigger an incremental SharePoint sync for one bot immediately, instead
    of waiting for its cron schedule (indexing.schedule). Runs in the
    background - poll GET /admin/index-status to see doc/chunk counts update."""
    registry.get_any(bot_id)   # raises BotNotFoundError (404) for an unknown id; disabled is fine
    background_tasks.add_task(sync_one_bot, bot_id, full=False)
    return {"status": "sync_started", "bot_id": bot_id}


@router.post("/bots/{bot_id}/reindex")
def reindex_bot_now(bot_id: str, background_tasks: BackgroundTasks) -> dict:
    """Force a full re-crawl of one bot: resets its saved delta token first,
    so every document is re-fetched and re-chunked even if SharePoint's delta
    query would otherwise report nothing changed. Runs in the background."""
    registry.get_any(bot_id)
    background_tasks.add_task(sync_one_bot, bot_id, full=True)
    return {"status": "reindex_started", "bot_id": bot_id}


# ---------- usage dashboard ----------

@router.get("/usage/summary")
def usage_summary(bot_id: str | None = None, period: str | None = None,
                  start: datetime | None = None, end: datetime | None = None,
                  db: Session = Depends(get_session)) -> dict:
    s, e = resolve_range(period, start, end)
    return usage.usage_summary(db, bot_id, s, e)


@router.get("/usage/trend")
def usage_trend(bot_id: str | None = None, granularity: str = "day",
                period: str | None = None, start: datetime | None = None,
                end: datetime | None = None, db: Session = Depends(get_session)) -> list[dict]:
    s, e = resolve_range(period, start, end)
    return usage.usage_trend(db, bot_id, s, e, granularity=granularity)


# ---------- cost dashboard ----------

@router.get("/cost/summary")
def cost_summary(bot_id: str | None = None, period: str | None = None,
                 start: datetime | None = None, end: datetime | None = None,
                 db: Session = Depends(get_session)) -> dict:
    s, e = resolve_range(period, start, end)
    return usage.cost_summary(db, bot_id, s, e)


@router.get("/cost/by-bot")
def cost_by_bot(period: str | None = None, start: datetime | None = None,
                end: datetime | None = None, db: Session = Depends(get_session)) -> list[dict]:
    s, e = resolve_range(period, start, end)
    return usage.cost_by_bot(db, None, s, e)


@router.get("/cost/by-model")
def cost_by_model(period: str | None = None, start: datetime | None = None,
                  end: datetime | None = None, db: Session = Depends(get_session)) -> list[dict]:
    s, e = resolve_range(period, start, end)
    return usage.cost_by_model(db, None, s, e)


@router.get("/cost/by-user")
def cost_by_user(bot_id: str | None = None, period: str | None = None,
                 start: datetime | None = None, end: datetime | None = None,
                 db: Session = Depends(get_session)) -> list[dict]:
    s, e = resolve_range(period, start, end)
    return usage.cost_by_user(db, bot_id, s, e)


# ---------- user analytics ----------

@router.get("/users")
def user_analytics(bot_id: str | None = None, period: str | None = None,
                   start: datetime | None = None, end: datetime | None = None,
                   db: Session = Depends(get_session)) -> dict:
    s, e = resolve_range(period, start, end)
    return {**users_repo.user_counts(db, bot_id, s, e),
            "users": users_repo.users(db, bot_id, s, e)}


# ---------- chat history ----------

@router.get("/chat-history")
def chat_history(bot_id: str | None = None, user_id: str | None = None,
                 keyword: str | None = None, period: str | None = None,
                 start: datetime | None = None, end: datetime | None = None,
                 limit: int = Query(100, le=500),
                 db: Session = Depends(get_session)) -> list[dict]:
    s, e = resolve_range(period, start, end)
    rows = search_chats(db, bot_id=bot_id, user_id=user_id, start=s, end=e,
                        keyword=keyword, limit=limit)
    return [{"id": r.id, "bot_id": r.bot_id, "user_id": r.user_id, "user_email": r.user_email,
             "question": r.question, "answer": r.answer, "model": r.model,
             "total_tokens": r.total_tokens, "cost_usd": r.cost_usd,
             "response_time_ms": r.response_time_ms, "created_at": r.created_at.isoformat()}
            for r in rows]


# ---------- logs & monitoring ----------

@router.get("/logs")
def logs(type: str | None = None, bot_id: str | None = None,
         period: str | None = None, start: datetime | None = None,
         end: datetime | None = None, limit: int = Query(200, le=1000),
         db: Session = Depends(get_session)) -> list[dict]:
    s, e = resolve_range(period, start, end)
    return search_events(db, type=type, bot_id=bot_id, start=s, end=e, limit=limit)
