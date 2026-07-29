"""The BotConfig schema. Every config/bots/*.yaml is validated against this
at startup, so a malformed bot fails loudly on load instead of at runtime.
"""
from pydantic import BaseModel, Field


class SharePointConfig(BaseModel):
    tenant: str                       # which M365 tenant (multi-tenant support)
    site_url: str
    libraries: list[str] = Field(default_factory=list)

    # Column-based publish gate + metadata. Defaults match the agreed columns;
    # override here if a tenant's internal column names differ. Only documents
    # whose `status_column` equals `published_value` get indexed.
    status_column: str = "Status"
    published_value: str = "Published"
    category_column: str = "Category"
    subcategory_column: str = "SubCategory"


class VectorStoreConfig(BaseModel):
    collection: str                   # this bot's Qdrant collection (isolation)


class ModelsConfig(BaseModel):
    llm: str = "gpt-4o-mini"
    embedding: str = "bge-base-en-v1.5"


class PromptConfig(BaseModel):
    system: str
    temperature: float = 0.2


class IndexingConfig(BaseModel):
    schedule: str = "0 2 * * *"       # cron; when this bot re-syncs SharePoint
    chunk_size: int = 800
    chunk_overlap: int = 100


class AccessConfig(BaseModel):
    allowed_groups: list[str] = Field(default_factory=list)  # Entra group IDs


class BotConfig(BaseModel):
    id: str
    name: str
    route: str
    enabled: bool = True
    sharepoint: SharePointConfig
    vectorstore: VectorStoreConfig
    models: ModelsConfig = Field(default_factory=ModelsConfig)
    prompt: PromptConfig
    indexing: IndexingConfig = Field(default_factory=IndexingConfig)
    access: AccessConfig = Field(default_factory=AccessConfig)
