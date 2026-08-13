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


class SourceWeights(BaseModel):
    """Optional per-source relevance score multipliers for list+library bots.
    Applied to every hit's raw vector similarity score BEFORE the two sources'
    results are merged and ranked together. Defaults to 1.0 / 1.0 (equal
    peers, unweighted merge). Set library > 1.0 to bias toward KB documents,
    or list > 1.0 to bias toward resolved tickets - useful when one source is
    consistently higher quality for this bot's domain. The weight is a
    multiplier, not a probability, so values above 1.0 are valid and just
    mean "boost this source's hits relative to the other's"."""
    library: float = Field(default=1.0, gt=0.0)
    list: float = Field(default=1.0, gt=0.0)


class ListPlusLibraryConfig(BaseModel):
    """Configuration for content_type='list+library' bots only.

    A list+library bot answers from two independent SharePoint sources at the
    same time - a document library (KB files, chunked and embedded) and a
    SharePoint List (e.g. resolved helpdesk tickets, row-per-item). Both
    sources are ALWAYS queried; there is no sequential fallback and no
    'did source A answer?' gate. Results are merged by relevance score.

    Why a separate config block (not reusing sharepoint.sites)?
    The existing SharePointConfig.sites entries mix libraries and lists on the
    SAME site, but a list+library bot needs two INDEPENDENT groups - one set
    of sites that contribute libraries, and a separate set of sites that
    contribute lists. Merging them into one site entry would require each
    SharePointSite to carry both a libraries: and a lists: key, which is
    already valid in the schema - but the existing _valid_content_source
    validator explicitly forbids that combination to keep library and list
    bots from accidentally mixing sources. Rather than carving an exception
    into that validator (which exists to guard against misconfiguration),
    list+library gets its own top-level config key with its own named fields:
    library_sites (which sites + libraries to crawl) and list_sites (which
    sites + lists to crawl). The ingestion layer calls the SAME run_sync() and
    run_list_sync() helpers as single-source bots - no new indexing code."""

    # Sites that contribute document libraries (KB files, chunked + embedded).
    # Same shape as SharePointConfig.sites - each entry has a site_url and
    # a list of library names on that site. Only libraries[] is used here;
    # lists[] on any entry is ignored (and rejected by the validator below).
    library_sites: list[SharePointSite] = Field(default_factory=list)

    # Sites that contribute SharePoint Lists (structured rows, e.g. resolved
    # tickets). Only lists[] is used here; libraries[] on any entry is ignored
    # (and rejected by the validator below).
    list_sites: list[SharePointSite] = Field(default_factory=list)

    # SharePoint tenant slug - which M365 tenant to authenticate against.
    # Required; both library_sites and list_sites must live in this tenant.
    tenant: str

    # Solved-gate: only rows whose `solved_status_column` equals
    # `solved_status_value` (case/whitespace-insensitive) are indexed from
    # the list source. Rows that don't match are excluded from the vector
    # store entirely (not just ranked lower), so only resolved/solved items
    # can ever appear in answers. If the column is absent on a row (some
    # lists have no status column at all), the row is included - same
    # optional-gate logic as _is_list_item_published in sync_job.py.
    solved_status_column: str = "Status"
    solved_status_value: str = "Solved"

    # Standard SharePoint metadata columns, read at ingestion time and stored
    # as chunk payload - same defaults as SharePointConfig's counterparts.
    category_column: str = "Category"
    subcategory_column: str = "SubCategory"

    # Per-source score multipliers applied before the merged rank. Both
    # default to 1.0 so omitting this block means equal-weight merge.
    source_weights: SourceWeights = Field(default_factory=SourceWeights)

    @model_validator(mode="after")
    def _valid_sites(self) -> "ListPlusLibraryConfig":
        """Ensure library_sites only carry libraries and list_sites only carry
        lists - catching misconfigured YAMLs at load time rather than
        silently ignoring the wrong side."""
        for site in self.library_sites:
            if site.lists:
                raise ValueError(
                    f"list+library bot: library_sites entry for '{site.site_url}' has "
                    "'lists' configured - only 'libraries' are valid here. "
                    "Move list sources into 'list_sites'."
                )
        for site in self.list_sites:
            if site.libraries:
                raise ValueError(
                    f"list+library bot: list_sites entry for '{site.site_url}' has "
                    "'libraries' configured - only 'lists' are valid here. "
                    "Move library sources into 'library_sites'."
                )
        # A library and a list sharing both a site_url AND a name would
        # collide in SyncState (keyed bot_id/site_url/name) - both sides of a
        # list+library bot share one real bot_id, unlike separate bots which
        # never share a SyncState keyspace with each other.
        for lib_site in self.library_sites:
            for list_site in self.list_sites:
                if lib_site.site_url != list_site.site_url:
                    continue
                shared = set(lib_site.libraries) & set(list_site.lists)
                if shared:
                    raise ValueError(
                        f"list+library bot: '{lib_site.site_url}' has a name used as both "
                        f"a library and a list ({sorted(shared)}) - library and list names "
                        "on the same site must be distinct."
                    )
        return self


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
    # Required for library/list/web bots. Optional at the field level (rather
    # than always-required) so a list+library bot can omit it entirely and use
    # library_collection/list_collection instead - enforced in
    # BotConfig._valid_content_source, same pattern as sharepoint/web being
    # optional fields with their requiredness enforced there too.
    collection: str | None = None
    # list+library bots only - two REAL, separate Qdrant collections (not one
    # shared collection tagged by source) so the library and list sides stay
    # fully isolated for citations/reconcile/delete_stale, exactly like every
    # other bot's single collection is isolated from every other bot's.
    library_collection: str | None = None
    list_collection: str | None = None


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
    # Lead-image display, gated by ORIGIN not just presence - feeds are the
    # publisher's own media tags (media:thumbnail/media:content/enclosure),
    # HTML-scraped og:image/twitter:image is more speculative. Enforced at
    # fetch time (app/ingestion/web_fetcher.py's fetch_source), not display
    # time - a bot set to "off" never even stores an image_url.
    show_images: Literal["feeds_only", "all", "off"] = "feeds_only"


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
    # (SharePoint List rows, one row = one chunk), a "Web bot" (scrapes
    # an admin-maintained list of URLs into the same Qdrant vector path a
    # library bot uses - see app/ingestion/web_fetcher.py), or a
    # "List+Library bot" (answers from BOTH a document library AND a
    # SharePoint List simultaneously - results merged by relevance, no
    # sequential fallback - see ListPlusLibraryConfig). Never more than one
    # at once for library/list/web; list+library is the only hybrid type and
    # carries its own config block (list_plus_library) below.
    content_type: Literal["library", "list", "web", "list+library"] = "library"
    # List bots only: also sync each SharePoint List's rows into its own typed
    # Postgres table (app/db/list_tables.py), alongside the existing Qdrant
    # embedding - similarity search alone can't answer exact counts/filters/
    # joins. Ignored for library/web/list+library bots. Defaults on so this
    # is automatic, per-bot opt-out only if a specific list bot doesn't need it.
    structured_store: bool = True
    # Required for library/list bots, unset for web and list+library bots
    # (which use `web` or `list_plus_library` below instead) - see
    # _valid_content_source.
    sharepoint: SharePointConfig | None = None
    # Web bots only - see WebSourceConfig.
    web: WebSourceConfig | None = None
    # list+library bots only - see ListPlusLibraryConfig.
    list_plus_library: ListPlusLibraryConfig | None = None
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
            if not self.vectorstore.collection:
                raise ValueError(
                    f"Bot '{self.id}': content_type '{self.content_type}' requires "
                    "'vectorstore.collection' to be set."
                )
            return self

        if self.content_type == "list+library":
            if self.list_plus_library is None:
                raise ValueError(
                    f"Bot '{self.id}': content_type is 'list+library' but no "
                    "'list_plus_library' config block is set - see ListPlusLibraryConfig."
                )
            if self.sharepoint is not None:
                raise ValueError(
                    f"Bot '{self.id}': content_type 'list+library' bots are configured "
                    "under 'list_plus_library', not 'sharepoint' - remove 'sharepoint'."
                )
            if self.web is not None:
                raise ValueError(
                    f"Bot '{self.id}': content_type 'list+library' bots cannot have a "
                    "'web' config block - remove 'web'."
                )
            cfg = self.list_plus_library
            if not cfg.library_sites or not any(site.libraries for site in cfg.library_sites):
                raise ValueError(
                    f"Bot '{self.id}': list+library requires at least one library_sites "
                    "entry with at least one library name."
                )
            if not cfg.list_sites or not any(site.lists for site in cfg.list_sites):
                raise ValueError(
                    f"Bot '{self.id}': list+library requires at least one list_sites "
                    "entry with at least one list name."
                )
            # Two REAL collections, not one shared one - see VectorStoreConfig.
            if not self.vectorstore.library_collection or not self.vectorstore.list_collection:
                raise ValueError(
                    f"Bot '{self.id}': content_type 'list+library' requires both "
                    "'vectorstore.library_collection' and 'vectorstore.list_collection' "
                    "to be set (not 'vectorstore.collection', which is for single-source bots)."
                )
            if self.vectorstore.collection:
                raise ValueError(
                    f"Bot '{self.id}': content_type 'list+library' bots use "
                    "'library_collection'/'list_collection', not 'collection' - remove it."
                )
            if self.vectorstore.library_collection == self.vectorstore.list_collection:
                raise ValueError(
                    f"Bot '{self.id}': 'library_collection' and 'list_collection' must be "
                    "different Qdrant collections, not the same name."
                )
            return self

        if self.sharepoint is None:
            raise ValueError(
                f"Bot '{self.id}': content_type '{self.content_type}' requires a "
                "'sharepoint' config block."
            )
        if not self.vectorstore.collection:
            raise ValueError(
                f"Bot '{self.id}': content_type '{self.content_type}' requires "
                "'vectorstore.collection' to be set."
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
