"""Dependency injection: builds the vector store, LLM client and pipeline once
and hands them to routes. Swapping backends happens HERE, driven by settings.
Also provides the auth dependencies (current user, admin gate).
"""
import threading
from functools import lru_cache

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.config import get_settings
from app.core.exceptions import ConfigError
from app.core.security import (
    AuthError,
    ForbiddenError,
    User,
    dev_user,
    get_validator,
)
from app.llm.azure_openai import AzureOpenAIClient
from app.llm.base import LLMClient
from app.rag.pipeline import RagPipeline
from app.vectorstore.base import VectorStore
from app.vectorstore.qdrant_store import QdrantVectorStore

# auto_error=False so we can raise our own clean 401 instead of FastAPI's default
_bearer = HTTPBearer(auto_error=False)


def get_current_user(
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> User:
    """Validate the Bearer token and return the signed-in user.
    If auth is disabled (local dev), returns a synthetic dev user instead."""
    if not get_settings().auth_enabled:
        return dev_user()
    if creds is None or not creds.credentials:
        raise AuthError("Missing Bearer token")
    return get_validator().validate(creds.credentials)


def require_admin(user: User = Depends(get_current_user)) -> User:
    """Allow only members of the active tenant's admin group (bypassed in dev)."""
    from app.core.security import get_admin_group_id

    if not get_settings().auth_enabled:
        return user
    admin_group = get_admin_group_id()
    if not admin_group:
        raise ForbiddenError(
            f"Admin group not configured. Set "
            f"{get_settings().auth_env_prefix()}_ADMIN_GROUP_ID."
        )
    if admin_group not in user.groups:
        raise ForbiddenError("Admin access required")
    return user


@lru_cache
def get_vector_store() -> VectorStore:
    s = get_settings()
    if s.vector_backend == "qdrant":
        return QdrantVectorStore(url=s.qdrant_url, api_key=s.qdrant_api_key)
    if s.vector_backend == "azure_search":
        from app.vectorstore.azure_search_store import AzureSearchVectorStore
        return AzureSearchVectorStore(endpoint=s.qdrant_url, api_key=s.qdrant_api_key or "")
    raise ConfigError(f"Unknown vector_backend '{s.vector_backend}'")


def _build_chat_client(s) -> AzureOpenAIClient:
    if s.llm_backend == "azure_openai":
        if not (s.azure_openai_endpoint and s.azure_openai_api_key):
            raise ConfigError("Azure OpenAI endpoint/key not configured (.env)")
        return AzureOpenAIClient(
            endpoint=s.azure_openai_endpoint,
            api_key=s.azure_openai_api_key,
            api_version=s.azure_openai_api_version,
        )
    raise ConfigError(f"Unknown llm_backend '{s.llm_backend}'")


# Plain @lru_cache doesn't stop two concurrent first-callers from both
# running the function body before either result is cached - FastAPI resolves
# sync dependencies in a threadpool, so two requests arriving close together
# right after a restart both entered this function before it returned.
# Building LocalEmbeddingModel (sentence-transformers -> torch) twice at once
# is not thread-safe: the second construction can observe the first's
# partially-initialized model and fail with "Cannot copy out of meta tensor;
# no data!" - a crash that only ever shows up under this exact race, and only
# once, right after a restart (once one construction wins and the module-
# level cache below is populated, every later call just reuses it).
_llm_client_lock = threading.Lock()
_llm_client_instance: "LLMClient | None" = None


def get_llm_client() -> LLMClient:
    global _llm_client_instance
    if _llm_client_instance is not None:
        return _llm_client_instance

    with _llm_client_lock:
        if _llm_client_instance is None:
            s = get_settings()
            chat_client = _build_chat_client(s)

            if s.embedding_backend == "azure_openai":
                _llm_client_instance = chat_client  # AzureOpenAIClient handles both chat and embed itself
            elif s.embedding_backend == "local":
                from app.llm.hybrid import HybridLLMClient
                from app.llm.local_embedding import LocalEmbeddingModel
                _llm_client_instance = HybridLLMClient(chat_client, LocalEmbeddingModel(s.local_embedding_model))
            else:
                raise ConfigError(f"Unknown embedding_backend '{s.embedding_backend}'")

    return _llm_client_instance


@lru_cache
def get_pipeline() -> RagPipeline:
    return RagPipeline(get_vector_store(), get_llm_client())
