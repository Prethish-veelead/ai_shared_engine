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
from app.db.repositories.chat_repository import feedback_comments_for, feedback_counts_by_bot, search_chats
from app.db.repositories.log_repository import search_events
from app.db.session import get_session
from app.llm.base import LLMClient
from app.monitoring.activity import activity_by_bot
from app.monitoring.resources import get_resources as get_system_resources
from app.monitoring.storage import get_storage_by_bot
from app.workers.sync_scheduler import sync_one_bot
from app.workers.web_sync import WEB_SYNC_LIBRARY

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
        # tenant + the SharePoint column-gate fields have no form UI of
        # their own yet, but MUST round-trip through edit -> save or every
        # save silently resets them to schema defaults (see toBotConfigPayload
        # in the admin-portal, which now preserves whatever it's handed here).
        "tenant": (
            b.sharepoint.tenant if b.sharepoint
            else b.web.tenant if b.web
            else b.list_plus_library.tenant if b.list_plus_library
            else None
        ),
        # sharepoint is null for content_type=web/list+library bots (they use
        # `web`/`list_plus_library` instead - see app/bots/schema.py's
        # _valid_content_source).
        # Publish Gate fields are per-site (SharePointSite), not per-bot - see
        # app/bots/schema.py's SharePointSite docstring - so each site entry
        # round-trips its own requirePublishGate/statusColumn/publishedValue.
        "sharepointSites": [{
            "siteUrl": s.site_url, "libraries": s.libraries, "lists": s.lists,
            "requirePublishGate": s.require_publish_gate,
            "statusColumn": s.status_column, "publishedValue": s.published_value,
        } for s in b.sharepoint.sites] if b.sharepoint else [],
        # List-bot-only gate fields (see SharePointConfig.status_column's
        # docstring) - unrelated to the per-site library Publish Gate above.
        "sharepointStatusColumn": b.sharepoint.status_column if b.sharepoint else None,
        "sharepointPublishedValue": b.sharepoint.published_value if b.sharepoint else None,
        "sharepointCategoryColumn": b.sharepoint.category_column if b.sharepoint else None,
        "sharepointSubcategoryColumn": b.sharepoint.subcategory_column if b.sharepoint else None,
        "webSource": ({
            "siteUrl": b.web.site_url, "sourceList": b.web.source_list,
            "idColumn": b.web.id_column, "urlColumn": b.web.url_column,
            "enableColumn": b.web.enable_column, "enabledValue": b.web.enabled_value,
            "categoryColumn": b.web.category_column or "",
            "showImages": b.web.show_images,
        } if b.web else None),
        # list+library bots only - round-trips the whole config block so an
        # edit -> save doesn't silently reset any of it (the same bug class
        # this function's docstring already fixed for sharepoint/web).
        "listPlusLibrary": ({
            # Publish Gate fields are per-site here too (same SharePointSite
            # type as sharepointSites above) - librarySites entries round-trip
            # their own requirePublishGate/statusColumn/publishedValue.
            "librarySites": [{
                "siteUrl": s.site_url, "libraries": s.libraries, "lists": s.lists,
                "requirePublishGate": s.require_publish_gate,
                "statusColumn": s.status_column, "publishedValue": s.published_value,
            } for s in b.list_plus_library.library_sites],
            "listSites": [{"siteUrl": s.site_url, "libraries": s.libraries, "lists": s.lists} for s in b.list_plus_library.list_sites],
            "solvedStatusColumn": b.list_plus_library.solved_status_column,
            "solvedStatusValue": b.list_plus_library.solved_status_value,
            "categoryColumn": b.list_plus_library.category_column,
            "subcategoryColumn": b.list_plus_library.subcategory_column,
            "sourceWeights": {
                "library": b.list_plus_library.source_weights.library,
                "list": b.list_plus_library.source_weights.list,
            },
            "retrievalMode": b.list_plus_library.retrieval_mode,
            "libraryCollection": b.vectorstore.library_collection,
            "listCollection": b.vectorstore.list_collection,
        } if b.list_plus_library else None),
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
        # Filtered to the bot's CURRENT (site_url, library/list) set - a
        # renamed or removed library leaves its old SyncState row behind
        # (config_writer.update_bot only purges rows on delete_bot, not on a
        # plain edit), and counting every row ever created for this bot_id
        # let a stale row for the OLD name stand in for the new one, making
        # "all_libraries_synced" true even though the renamed library itself
        # was never actually synced.
        # content_type=web bots have no per-library/list breakdown - the
        # whole bot's sync is one SyncState row, keyed with a sentinel
        # "library" name (app/workers/web_sync.py's WEB_SYNC_LIBRARY).
        # content_type=list+library bots have no `bot.sharepoint` at all (its
        # two site groups live under bot.list_plus_library instead) and write
        # to TWO collections, so both need their own branch here.
        if bot.content_type == "chat":
            # No data source, no Qdrant collection, nothing ever synced -
            # store.index_stats(None) would be an unguarded None pass-through
            # for this content type, so short-circuit before reaching it.
            stats = {"documents": 0, "chunks": 0}
            current_keys = set()
            total_libraries = 0
        elif bot.content_type == "web":
            stats = store.index_stats(bot.vectorstore.collection)
            current_keys = {(bot.web.site_url, WEB_SYNC_LIBRARY)}
            total_libraries = 1
        elif bot.content_type == "list+library":
            cfg = bot.list_plus_library
            lib_stats = store.index_stats(bot.vectorstore.library_collection)
            list_stats = store.index_stats(bot.vectorstore.list_collection)
            stats = {
                "documents": lib_stats["documents"] + list_stats["documents"],
                "chunks": lib_stats["chunks"] + list_stats["chunks"],
            }
            current_keys = {
                (site.site_url, name) for site in cfg.library_sites for name in site.libraries
            } | {
                (site.site_url, name) for site in cfg.list_sites for name in site.lists
            }
            total_libraries = (
                sum(len(site.libraries) for site in cfg.library_sites)
                + sum(len(site.lists) for site in cfg.list_sites)
            )
        else:
            stats = store.index_stats(bot.vectorstore.collection)
            current_keys = {
                (site.site_url, name)
                for site in (bot.sharepoint.sites if bot.sharepoint else [])
                for name in (*site.libraries, *site.lists)
            }
            # A bot only ever populates one of libraries/lists (see BotConfig.
            # content_type), so summing both here just counts "sync units"
            # generically without needing to branch on library vs list.
            total_libraries = sum(
                len(site.libraries) + len(site.lists) for site in (bot.sharepoint.sites if bot.sharepoint else [])
            )
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


@router.get("/sharepoint/list-columns")
def sharepoint_list_columns(site_url: str, list_name: str,
                             tenant: str = "veelead-development") -> list[str]:
    """Return the non-system column names for a specific SharePoint List.
    Used by the list+library bot form to let the admin pin a 'solved_status_column'
    without having to know the internal Graph field name in advance.

    Implementation: fetches up to 20 real rows, unions all field keys across
    them, subtracts the known system fields (app/ingestion/indexer.LIST_SYSTEM_FIELDS)
    that are present on every list regardless of its schema, and returns the
    remainder sorted. No Graph /columns endpoint needed - real rows always
    expose the real columns, and this approach surfaces internal field names
    (e.g. 'TicketStatus', not 'Status') exactly as they appear in the data,
    which is what the gate comparison uses.

    Called from the admin portal's 'Load Columns' button in the solved-gate
    section of the list+library bot creation form."""
    from app.ingestion.indexer import LIST_SYSTEM_FIELDS
    from app.ingestion.sharepoint_client import SharePointClient
    from app.ingestion.tenant_resolver import resolve_tenant

    creds = resolve_tenant(tenant)
    client = SharePointClient(creds.tenant_id, creds.client_id, creds.client_secret)
    try:
        site_id = client.resolve_site(site_url)
        all_lists = client.resolve_lists(site_id)
        if list_name not in all_lists:
            raise UpstreamError(
                f"List '{list_name}' not found on site '{site_url}'. "
                f"Available: {sorted(all_lists)}"
            )
        list_id = all_lists[list_name]
        # Fetch a sample of rows to discover columns. 20 rows is enough to
        # catch optional columns that don't appear on every row (e.g. a
        # 'Resolution' column only filled in when a ticket is closed). Full
        # list_items() would work too but is unnecessarily heavy for large lists.
        items = client.list_items(site_id, list_id)
        sample = items[:20] if len(items) > 20 else items
    except UpstreamError:
        raise
    except Exception as exc:
        raise UpstreamError(f"Failed to fetch columns for list '{list_name}': {exc}") from exc

    seen: set[str] = set()
    for item in sample:
        seen.update(item.fields.keys())

    # Strip system/plumbing fields and '@odata.*' metadata keys - these are
    # present on every Graph list item regardless of schema and are not real
    # business columns an admin would want to filter on.
    extra_system = {"id", "Title", "Modified", "Created", "Author", "Editor"}
    columns = sorted(
        col for col in seen
        if col not in LIST_SYSTEM_FIELDS
        and col not in extra_system
        and not col.startswith("@")
    )
    return columns


@router.get("/sharepoint/list-column-values")
def sharepoint_list_column_values(site_url: str, list_name: str, column: str,
                                   tenant: str = "veelead-development") -> list[str]:
    """Return the distinct non-null string values for one column in a SharePoint
    List, capped at 200. Used by the list+library bot form's 'Load Values' button
    so the admin can pick the exact 'solved_status_value' (e.g. 'Solved',
    'Closed', 'Resolved') from a dropdown rather than guessing.

    Fetches all rows (list_items does paged Graph requests already), collects
    unique values for the requested column, sorts and caps them. String-coerces
    all values so numeric/boolean columns still produce useful dropdown entries."""
    from app.ingestion.sharepoint_client import SharePointClient
    from app.ingestion.tenant_resolver import resolve_tenant

    creds = resolve_tenant(tenant)
    client = SharePointClient(creds.tenant_id, creds.client_id, creds.client_secret)
    try:
        site_id = client.resolve_site(site_url)
        all_lists = client.resolve_lists(site_id)
        if list_name not in all_lists:
            raise UpstreamError(
                f"List '{list_name}' not found on site '{site_url}'. "
                f"Available: {sorted(all_lists)}"
            )
        list_id = all_lists[list_name]
        items = client.list_items(site_id, list_id)
    except UpstreamError:
        raise
    except Exception as exc:
        raise UpstreamError(
            f"Failed to fetch values for column '{column}' in list '{list_name}': {exc}"
        ) from exc

    _MAX_VALUES = 200
    seen: set[str] = set()
    for item in items:
        raw = item.fields.get(column)
        if raw is None or raw == "":
            continue
        seen.add(str(raw).strip())
        if len(seen) >= _MAX_VALUES:
            break
    return sorted(seen)


# A SharePoint document library's /delta response never reliably includes
# listItem fields (see SharePointClient.get_fields's docstring - "Delta
# responses don't reliably include these, so we fetch per changed item"),
# unlike a plain List's /items?$expand=fields, which returns every row's
# fields in one paged call. Discovering a library's columns/values therefore
# costs one EXTRA Graph call per sampled file, so both are capped at a
# smaller sample than the list endpoints above to bound how many of those
# calls one "Load Columns"/"Load Values" click makes.
_LIBRARY_COLUMN_SAMPLE_SIZE = 20
_LIBRARY_VALUE_SAMPLE_SIZE = 200


@router.get("/sharepoint/library-columns")
def sharepoint_library_columns(site_url: str, library_name: str,
                                tenant: str = "veelead-development") -> list[str]:
    """Return the non-system column names for a specific SharePoint document
    library - the library-side counterpart of sharepoint_list_columns above.
    Used by the Publish Gate section of both the plain library bot form and
    the list+library bot's Library Sites block, so the admin can pin a
    'status_column' without knowing the internal Graph field name in advance.

    Samples up to _LIBRARY_COLUMN_SAMPLE_SIZE files, unions their listItem
    field keys, and subtracts the same known system-field set
    sharepoint_list_columns already strips (a document library's files
    carry the same SharePoint listItem plumbing fields a plain List's rows
    do, since a library is a list under the hood too)."""
    from app.ingestion.indexer import LIST_SYSTEM_FIELDS
    from app.ingestion.sharepoint_client import SharePointClient
    from app.ingestion.tenant_resolver import resolve_tenant

    creds = resolve_tenant(tenant)
    client = SharePointClient(creds.tenant_id, creds.client_id, creds.client_secret)
    try:
        site_id = client.resolve_site(site_url)
        all_drives = client.resolve_drives(site_id)
        if library_name not in all_drives:
            raise UpstreamError(
                f"Library '{library_name}' not found on site '{site_url}'. "
                f"Available: {sorted(all_drives)}"
            )
        drive_id = all_drives[library_name]
        items, _next_delta = client.delta(drive_id, None)
        sample = [item for item in items if not item.deleted][:_LIBRARY_COLUMN_SAMPLE_SIZE]
        seen: set[str] = set()
        for item in sample:
            seen.update(client.get_fields(drive_id, item.doc_id).keys())
    except UpstreamError:
        raise
    except Exception as exc:
        raise UpstreamError(f"Failed to fetch columns for library '{library_name}': {exc}") from exc

    extra_system = {"id", "Title", "Modified", "Created", "Author", "Editor"}
    return sorted(
        col for col in seen
        if col not in LIST_SYSTEM_FIELDS and col not in extra_system and not col.startswith("@")
    )


@router.get("/sharepoint/library-column-values")
def sharepoint_library_column_values(site_url: str, library_name: str, column: str,
                                      tenant: str = "veelead-development") -> list[str]:
    """Return the distinct non-null string values for one column across a
    sample of files in a SharePoint document library, capped at
    _LIBRARY_VALUE_SAMPLE_SIZE files scanned (bounding Graph calls - see the
    module-level comment above sharepoint_library_columns) and
    _LIBRARY_VALUE_SAMPLE_SIZE distinct values returned. Used by the Publish
    Gate section's 'Load Values' button so the admin can pick the exact
    'published_value' (e.g. 'Published', 'Approved') from a dropdown rather
    than guessing."""
    from app.ingestion.sharepoint_client import SharePointClient
    from app.ingestion.tenant_resolver import resolve_tenant

    creds = resolve_tenant(tenant)
    client = SharePointClient(creds.tenant_id, creds.client_id, creds.client_secret)
    try:
        site_id = client.resolve_site(site_url)
        all_drives = client.resolve_drives(site_id)
        if library_name not in all_drives:
            raise UpstreamError(
                f"Library '{library_name}' not found on site '{site_url}'. "
                f"Available: {sorted(all_drives)}"
            )
        drive_id = all_drives[library_name]
        items, _next_delta = client.delta(drive_id, None)
        sample = [item for item in items if not item.deleted][:_LIBRARY_VALUE_SAMPLE_SIZE]
        seen: set[str] = set()
        for item in sample:
            raw = client.get_fields(drive_id, item.doc_id).get(column)
            if raw is None or raw == "":
                continue
            seen.add(str(raw).strip())
            if len(seen) >= _LIBRARY_VALUE_SAMPLE_SIZE:
                break
    except UpstreamError:
        raise
    except Exception as exc:
        raise UpstreamError(
            f"Failed to fetch values for column '{column}' in library '{library_name}': {exc}"
        ) from exc
    return sorted(seen)


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
    comments = feedback_comments_for(db, [r.id for r in rows])
    return [{"id": r.id, "bot_id": r.bot_id, "user_id": r.user_id, "user_email": r.user_email,
             "question": r.question, "answer": r.answer, "model": r.model,
             "prompt_tokens": r.prompt_tokens, "completion_tokens": r.completion_tokens,
             "total_tokens": r.total_tokens, "cost_usd": r.cost_usd,
             "response_time_ms": r.response_time_ms, "created_at": r.created_at.isoformat(),
             "feedback": r.feedback, "feedback_comment": comments.get(r.id)}
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
