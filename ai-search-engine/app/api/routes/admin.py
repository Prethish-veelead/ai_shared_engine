"""Admin API — the endpoints the admin portal (Antigravity) calls.
Shapes match docs/API_CONTRACT.md. Add Entra ID admin-role checks here before
exposing publicly (see core/security.py).
"""
from datetime import datetime

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query

from pydantic import BaseModel

from app.api.deps import get_current_user, get_llm_client, get_vector_store, require_admin
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.time_filters import resolve_range
from app.assistant.admin_assistant import ask_admin_assistant
from app.assistant.prompt_improver import improve_system_prompt
from app.bots import config_writer
from app.bots.registry import registry
from app.bots.schema import BotConfig
from app.core.config import get_settings
from app.core.exceptions import ConfigError, UpstreamError
from app.core.security import User
from app.db.models import SyncState
from app.db.repositories import usage_repository as usage
from app.db.repositories import user_repository as users_repo
from app.db.repositories.chat_repository import feedback_counts_by_bot, search_chats
from app.db.repositories.log_repository import search_events
from app.db.session import get_session
from app.llm.base import LLMClient
from app.monitoring.activity import activity_by_bot
from app.monitoring.resources import get_resources as get_system_resources
from app.monitoring.storage import get_storage_by_bot
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
        "contentType": b.content_type,
        "sharepointSites": [{"siteUrl": s.site_url, "libraries": s.libraries, "lists": s.lists} for s in b.sharepoint.sites],
        "qdrantCollection": b.vectorstore.collection,
        "llmModel": b.models.llm,
        "embeddingModel": b.models.embedding,
        "indexingSchedule": b.indexing.schedule,
        "systemPrompt": b.prompt.system,
        "access": {"allowed_groups": b.access.allowed_groups},
        "responseFields": [{"name": f.name, "prompt": f.prompt} for f in b.response_fields],
        "includeCategory": b.include_category,
        "sampleQuestions": b.sample_questions,
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

    feedback_by_bot = feedback_counts_by_bot(db)

    result = []
    for bot in bots:
        stats = store.index_stats(bot.vectorstore.collection)
        # Filtered to the bot's CURRENT (site_url, library/list) set - a
        # renamed or removed library leaves its old SyncState row behind
        # (config_writer.update_bot only purges rows on delete_bot, not on a
        # plain edit), and counting every row ever created for this bot_id
        # let a stale row for the OLD name stand in for the new one, making
        # "all_libraries_synced" true even though the renamed library itself
        # was never actually synced.
        current_keys = {
            (site.site_url, name)
            for site in bot.sharepoint.sites
            for name in (*site.libraries, *site.lists)
        }
        states = [s for s in states_by_bot.get(bot.id, []) if (s.site_url, s.library) in current_keys]
        # MIN across libraries, not MAX, and only once every configured
        # library has a row with a real last_run_at - a bot with N libraries
        # gets a separate SyncState row per library, each updated
        # independently as that library finishes. Using MAX meant this
        # flipped to a real timestamp the moment the FASTEST library
        # finished, which is what the admin-portal's sync-status polling
        # (bots/page.tsx) uses to decide "done" - so a multi-library sync
        # looked complete (and doc/chunk counts looked final) the instant
        # the first library finished, while the rest were still indexing in
        # the background. MIN only advances once the slowest/last library
        # is also done, and doubles as a more honest "how stale is this bot"
        # value in general (a bot is only as fresh as its stalest library).
        # A bot only ever populates one of libraries/lists (see BotConfig.
        # content_type), so summing both here just counts "sync units"
        # generically without needing to branch on content_type.
        total_libraries = sum(len(site.libraries) + len(site.lists) for site in bot.sharepoint.sites)
        all_libraries_synced = bool(states) and len(states) >= total_libraries \
            and all(s.last_run_at is not None for s in states)
        last_run = min((s.last_run_at for s in states), default=None) if all_libraries_synced else None
        fb = feedback_by_bot.get(bot.id, {"likes": 0, "dislikes": 0})
        result.append({
            "bot_id": bot.id,
            "documents_indexed": stats["documents"],
            "chunks_indexed": stats["chunks"],
            "last_sync_at": last_run.isoformat() if last_run else None,
            "likes": fb["likes"],
            "dislikes": fb["dislikes"],
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
        # get_llm_client() (app/api/deps.py) picks the embedding backend
        # globally from settings.embedding_backend - a bot's models.embedding
        # field is never actually consulted to choose which embedder runs.
        # When embedding_backend=local, any Azure embedding deployment
        # (e.g. text-embedding-3-small, left over from before local
        # embeddings were adopted) is real but unusable: picking it in the
        # form would save a bot config that claims one model while every
        # document/query is still silently embedded with the local model.
        # So only list Azure embedding deployments here when they're the
        # backend actually in effect.
        if "embedding" in model:
            if s.embedding_backend == "azure_openai":
                embedding.append(name)
        else:
            llm.append(name)

    # Azure OpenAI only lists ITS OWN deployments - the locally-run embedding
    # model isn't an Azure deployment, so it would never appear above, and
    # the form couldn't offer the model that's actually configured on every
    # bot. Use the bare model name (strip the "BAAI/" org prefix) - that's
    # what bot YAMLs and usage_logs store; LOCAL_EMBEDDING_MODEL's full HF id
    # is only needed to load it.
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


@router.get("/sharepoint/lists")
def sharepoint_lists(site_url: str, tenant: str = "veelead-development") -> list[str]:
    """List the real SharePoint Lists at a site (excluding document libraries
    and hidden system lists - see SharePointClient.resolve_lists) - powers a
    List bot's form the same way sharepoint_libraries() powers a Library
    bot's."""
    from app.ingestion.sharepoint_client import SharePointClient
    from app.ingestion.tenant_resolver import resolve_tenant

    creds = resolve_tenant(tenant)
    client = SharePointClient(creds.tenant_id, creds.client_id, creds.client_secret)
    try:
        site_id = client.resolve_site(site_url)
        lists = client.resolve_lists(site_id)
    except Exception as exc:
        raise UpstreamError(f"Failed to resolve SharePoint site/lists: {exc}") from exc
    return sorted(lists.keys())


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
             "prompt_tokens": r.prompt_tokens, "completion_tokens": r.completion_tokens,
             "total_tokens": r.total_tokens, "cost_usd": r.cost_usd,
             "response_time_ms": r.response_time_ms, "created_at": r.created_at.isoformat(),
             "feedback": r.feedback}
            for r in rows]


# ---------- logs & monitoring ----------

@router.get("/logs")
def logs(type: str | None = None, bot_id: str | None = None,
         period: str | None = None, start: datetime | None = None,
         end: datetime | None = None, limit: int = Query(200, le=1000),
         db: Session = Depends(get_session)) -> list[dict]:
    s, e = resolve_range(period, start, end)
    return search_events(db, type=type, bot_id=bot_id, start=s, end=e, limit=limit)


# ---------- admin analytics assistant ----------

class AssistantAskRequest(BaseModel):
    question: str


@router.post("/assistant/ask")
def assistant_ask(payload: AssistantAskRequest, user: User = Depends(get_current_user),
                  llm: LLMClient = Depends(get_llm_client),
                  db: Session = Depends(get_session)) -> dict:
    answer = ask_admin_assistant(db, payload.question, llm, user.id)
    return {"answer": answer}


class ImprovePromptRequest(BaseModel):
    prompt: str


@router.post("/bots/improve-prompt")
def improve_prompt(payload: ImprovePromptRequest, user: User = Depends(get_current_user),
                   llm: LLMClient = Depends(get_llm_client),
                   db: Session = Depends(get_session)) -> dict:
    try:
        improved = improve_system_prompt(db, payload.prompt, llm, user.id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"improved_prompt": improved}


# ---------- resources (storage / system / activity) ----------
# Storage is exact (each bot owns its Qdrant collection and, for list bots,
# its own Postgres tables). RAM/CPU are NOT per-bot - all bots share one api
# container and one worker container, so there is no OS-level "this bot used
# X MB". System-level numbers are real; per-bot "activity" is an explicit
# load PROXY (requests/tokens/cost share), never presented as per-bot RAM/CPU.
# See docs/ADMIN_RESOURCES_PAGE.md.

@router.get("/storage/by-bot")
def storage_by_bot(db: Session = Depends(get_session)) -> list[dict]:
    return get_storage_by_bot(db, get_vector_store())


@router.get("/resources")
def resources() -> dict:
    return get_system_resources()


@router.get("/activity/by-bot")
def activity_by_bot_route(period: str | None = None, start: datetime | None = None,
                          end: datetime | None = None, db: Session = Depends(get_session)) -> list[dict]:
    s, e = resolve_range(period, start, end)
    return activity_by_bot(db, s, e)
    return {"improved_prompt": improved}
