"""The BotConfig schema. Every config/bots/*.yaml is validated against this
at startup, so a malformed bot fails loudly on load instead of at runtime.
"""
from typing import Literal

from pydantic import BaseModel, Field, model_validator


class SharePointSite(BaseModel):
    site_url: str
    libraries: list[str] = Field(default_factory=list)
    # SharePoint Lists (structured rows - Question/Answer/Category, not
    # files) this site contributes, for a "list" content_type bot. Kept on
    # the same site block as libraries so the admin form's multi-site
    # picker works identically for both - see BotConfig.content_type for why
    # a single bot only ever populates one of libraries/lists, not both.
    lists: list[str] = Field(default_factory=list)


class SharePointConfig(BaseModel):
    tenant: str                       # which M365 tenant (multi-tenant support)
    # A bot can pull from more than one SharePoint site, each with its own
    # set of libraries - e.g. an HR site's "Policies" library plus a
    # separate Onboarding site's "New Hire Guides" library, combined into
    # one bot. Library names are only unique WITHIN a site, so each site's
    # libraries are kept grouped with that site rather than flattened into
    # one list (a library named "Documents" can exist on more than one site).
    sites: list[SharePointSite] = Field(default_factory=list)

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


class WebSourceConfig(BaseModel):
    """content_type=web bots only: where to read the admin-maintained
    registry of URLs to scrape (a SharePoint List - NOT ingested as content
    itself, unlike a content_type=list bot's Lists; see app/ingestion/
    web_fetcher.py.read_web_sources) plus the fetch etiquette/behavior
    settings. Kept as its own block rather than reusing SharePointConfig's
    `sites: [...]` shape - a web bot has exactly one site + one URL-list,
    not a multi-site multi-library structure, and needs column-name
    mapping (id/url/enable/category) that library/list bots have no
    equivalent for."""
    tenant: str
    site_url: str
    source_list: str                       # the SharePoint LIST holding the URLs
    id_column: str = "ID"
    url_column: str = "URL"
    enable_column: str = "Enable"
    enabled_value: str = "yes"
    category_column: str | None = "Category"
    user_agent: str = "VeeleadBot/1.0 (+https://veelead.com)"
    request_timeout_s: int = 15
    per_host_delay_s: float = 1.0          # politeness between requests to the same host
    respect_robots: bool = True
    max_items_per_source: int = 25         # cap feed entries / links per source
    prefer_feeds: bool = True


class ResponseField(BaseModel):
    """One extra field a bot adds to its /ask response, on top of the fixed
    base fields (answer, citations, model, total_tokens, cost_usd,
    response_time_ms) - those never change shape for any bot. `prompt` tells
    the LLM what to generate for this field; it's produced in the SAME
    completion that generates the answer (see app/rag/prompt_builder.py),
    not a second LLM call.

    `type` only controls how the field is DESCRIBED to the model (a bare
    "[]"/"{}" placeholder in the JSON shape it's asked to return, vs a
    quoted string placeholder) - the backend never validates or coerces the
    parsed value against this, it's passed through as whatever JSON the
    model actually returned. Two field names are recognized specially by
    bot-ui: "follow_up_questions" (array of strings, rendered as clickable
    next-question chips) and "chart" (object, rendered as a bar/pie/line
    chart) - see docs on how to configure each. Any other name just rides
    along as an extra top-level AskResponse field, same as before."""
    name: str
    prompt: str
    type: Literal["string", "array", "object"] = "string"


# AskResponse's fixed base fields (app/api/routes/ask.py) - a response_fields
# entry sharing one of these names would collide with the same-named keyword
# argument in AskResponse(**result.extra_fields), raising a TypeError on
# every single call to that bot. Reject it at config-load time instead.
RESERVED_RESPONSE_FIELD_NAMES = {
    "answer", "citations", "model", "total_tokens", "cost_usd",
    "response_time_ms", "chat_log_id",
}


class BotConfig(BaseModel):
    id: str
    name: str
    route: str
    enabled: bool = True
    # A bot is a "Library bot" (files, chunked and embedded), a "List bot"
    # (SharePoint List rows, one row = one chunk), or a "Web bot" (scrapes
    # an admin-maintained list of URLs into the same Qdrant vector path a
    # library bot uses - see app/ingestion/web_fetcher.py) - never more than
    # one at once. Hybrid sources are a real future possibility but
    # deliberately out of scope for now; the validator below enforces it so
    # a misconfigured bot fails loudly at load instead of silently ignoring
    # half its configured sources.
    content_type: Literal["library", "list", "web"] = "library"
    # List bots only: also sync each SharePoint List's rows into its own typed
    # Postgres table (app/db/list_tables.py), alongside the existing Qdrant
    # embedding - similarity search alone can't answer exact counts/filters/
    # joins. Ignored for library/web bots. Defaults on so this is automatic,
    # per-bot opt-out only if a specific list bot doesn't need it.
    structured_store: bool = True
    # Required for library/list bots, unset for web bots (which use `web`
    # below instead) - see _valid_content_source.
    sharepoint: SharePointConfig | None = None
    # Web bots only - see WebSourceConfig.
    web: WebSourceConfig | None = None
    vectorstore: VectorStoreConfig
    models: ModelsConfig = Field(default_factory=ModelsConfig)
    prompt: PromptConfig
    indexing: IndexingConfig = Field(default_factory=IndexingConfig)
    access: AccessConfig = Field(default_factory=AccessConfig)
    # Both optional and additive - empty/false (the default) means today's
    # exact base-only response, unchanged.
    response_fields: list[ResponseField] = Field(default_factory=list)
    # Free: read straight off the top-cited chunk's SharePoint Category
    # column metadata (already stored on every chunk at ingestion time), no
    # extra LLM call.
    include_category: bool = False
    # Shown as clickable starter prompts in bot-ui's empty chat state, so a
    # new user sees what this specific bot can actually answer instead of a
    # blank box. Optional/additive - empty (the default) just means no
    # suggestions are shown, same as today.
    sample_questions: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _valid_content_source(self) -> "BotConfig":
        if self.content_type == "web":
            if self.web is None:
                raise ValueError(
                    f"Bot '{self.id}': content_type is 'web' but no 'web' config "
                    "block is set - see WebSourceConfig."
                )
            if self.sharepoint is not None:
                raise ValueError(
                    f"Bot '{self.id}': content_type is 'web' bots are configured "
                    "entirely under 'web', not 'sharepoint' - remove 'sharepoint'."
                )
            return self

        if self.sharepoint is None:
            raise ValueError(
                f"Bot '{self.id}': content_type '{self.content_type}' requires a "
                "'sharepoint' config block."
            )
        if self.content_type == "library":
            if any(site.lists for site in self.sharepoint.sites):
                raise ValueError(
                    f"Bot '{self.id}': content_type is 'library' but one or more "
                    "sites has 'lists' configured - a bot can't mix libraries and "
                    "lists yet. Remove 'lists' or set content_type: list."
                )
        else:
            if any(site.libraries for site in self.sharepoint.sites):
                raise ValueError(
                    f"Bot '{self.id}': content_type is 'list' but one or more "
                    "sites has 'libraries' configured - a bot can't mix libraries "
                    "and lists yet. Remove 'libraries' or set content_type: library."
                )
        return self

    @model_validator(mode="after")
    def _valid_response_fields(self) -> "BotConfig":
        for f in self.response_fields:
            if f.name in RESERVED_RESPONSE_FIELD_NAMES:
                raise ValueError(
                    f"Bot '{self.id}': response_fields entry '{f.name}' collides with "
                    f"a fixed base response field ({sorted(RESERVED_RESPONSE_FIELD_NAMES)}). "
                    "Pick a different name."
                )
        return self

    @model_validator(mode="after")
    def _valid_chunking(self) -> "BotConfig":
        if self.indexing.chunk_overlap >= self.indexing.chunk_size:
            raise ValueError(
                f"Bot '{self.id}': indexing.chunk_overlap ({self.indexing.chunk_overlap}) "
                f"must be smaller than indexing.chunk_size ({self.indexing.chunk_size}) - "
                "otherwise the chunker's sliding window never advances and hangs indefinitely "
                "on any document longer than one chunk."
            )
        return self
