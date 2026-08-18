"""Global application settings.

All values are read from environment variables (see .env.example).
Nothing here is bot-specific — per-bot settings live in config/bots/*.yaml.
"""
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv
from pydantic_settings import BaseSettings, SettingsConfigDict

# Load .env into the process environment so dynamic per-tenant credentials
# (e.g. VEELEAD_DEVELOPMENT_CLIENT_ID) are visible via os.environ. In Docker the
# compose env_file already injects these; this makes local runs work too.
load_dotenv()


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # --- App ---
    app_name: str = "AI Search Engine"
    environment: str = "development"
    config_dir: Path = Path("config")

    # --- Single-origin static frontends (docs/SINGLE_ORIGIN_DEPLOY.md) ---
    # Built by the frontend-build Docker stage; absent in plain local `uvicorn`
    # runs, which is fine - main.py only mounts a dir that actually exists.
    admin_static_dir: Path = Path("app/static/admin")
    root_static_dir: Path = Path("app/static/root")

    # --- Postgres (system of record: chat history, usage, config) ---
    postgres_dsn: str = "postgresql+psycopg://appuser:apppass@localhost:5432/aisearch"

    # --- Qdrant (vectors, one collection per bot) ---
    qdrant_url: str = "http://localhost:6333"
    qdrant_api_key: str | None = None

    # --- Azure OpenAI ---
    azure_openai_endpoint: str | None = None
    azure_openai_api_key: str | None = None
    azure_openai_api_version: str = "2024-10-21"

    # --- Which implementations to use (swap without code changes) ---
    vector_backend: str = "qdrant"          # qdrant | azure_search
    llm_backend: str = "azure_openai"        # azure_openai | ... (chat only)
    embedding_backend: str = "azure_openai"  # azure_openai | local
    local_embedding_model: str = "BAAI/bge-base-en-v1.5"  # used when embedding_backend=local

    # --- List bot structured query layer (app/rag/structured/) ---
    structured_query_max_tool_rounds: int = 5   # cap on LLM<->tool round trips per question
    structured_query_row_limit: int = 200       # cap on rows a single tool call can return

    # --- Temporary, non-persisted chat history (app/rag/history.py) ---
    # The browser resends recent turns with each /ask call; this bounds how
    # many of them the backend will actually use, regardless of how many the
    # client sends - latency/cost/context-window protection, not a session
    # limit (there is no session to limit).
    chat_history_max_messages: int = 8

    # --- Admin notification bell: resource threshold alerts (app/monitoring/alerts.py) ---
    resource_alert_threshold_pct: float = 90.0     # memory/disk %% that triggers an alert
    resource_alert_check_interval_minutes: int = 5  # how often the worker checks
    resource_alert_debounce_minutes: int = 30       # don't re-alert on the same metric within this window

    # --- Entra ID auth (Job B: user sign-in) ---
    auth_enabled: bool = True                # False = local dev bypass (see below)
    auth_tenant: str = "veelead-development"  # which tenant's users may sign in
    dev_user_groups: str = ""                 # comma-sep groups for the bypass dev user

    # --- Cross-origin API access (e.g. an SPFx web part on a SharePoint
    # origin calling /api/ask/* directly) - see docs/SPFX_API_ACCESS.md.
    # Comma-separated origins, e.g. "https://contoso.sharepoint.com". Empty
    # (the default) means NO CORSMiddleware is added at all - today's exact
    # same-origin-only behavior for bot-ui/admin-portal, unchanged. This is
    # purely about which browser origins may read the response; it has no
    # effect on token validation or identity/logging - those are unchanged
    # regardless of the caller's origin.
    cors_allowed_origins: str = ""

    def auth_env_prefix(self) -> str:
        """`veelead-development` -> `VEELEAD_DEVELOPMENT` (matches .env names)."""
        return self.auth_tenant.strip().upper().replace("-", "_").replace(" ", "_")

    def cors_allowed_origins_list(self) -> list[str]:
        return [o.strip() for o in self.cors_allowed_origins.split(",") if o.strip()]

    @property
    def bots_dir(self) -> Path:
        return self.config_dir / "bots"


@lru_cache
def get_settings() -> Settings:
    """Cached singleton so we parse env only once."""
    return Settings()
