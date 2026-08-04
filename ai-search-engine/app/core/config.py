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

    # --- Entra ID auth (Job B: user sign-in) ---
    auth_enabled: bool = True                # False = local dev bypass (see below)
    auth_tenant: str = "veelead-development"  # which tenant's users may sign in
    dev_user_groups: str = ""                 # comma-sep groups for the bypass dev user

    def auth_env_prefix(self) -> str:
        """`veelead-development` -> `VEELEAD_DEVELOPMENT` (matches .env names)."""
        return self.auth_tenant.strip().upper().replace("-", "_").replace(" ", "_")

    @property
    def bots_dir(self) -> Path:
        return self.config_dir / "bots"


@lru_cache
def get_settings() -> Settings:
    """Cached singleton so we parse env only once."""
    return Settings()
