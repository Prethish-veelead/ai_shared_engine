"""Database tables. These four cover chat history, usage/cost, and sync state.
Bot *config* lives in YAML; this Bot table is optional metadata / a future
target if you move config into the DB via the admin portal.
"""
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Float, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class ChatLog(Base):
    """One row per question answered. Drives the Chat History dashboard."""

    __tablename__ = "chat_logs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    bot_id: Mapped[str] = mapped_column(String(64), index=True)
    user_id: Mapped[str] = mapped_column(String(128), index=True)   # Entra object id
    user_email: Mapped[str | None] = mapped_column(String(256), nullable=True)
    question: Mapped[str] = mapped_column(Text)
    answer: Mapped[str] = mapped_column(Text)
    citations: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON string
    model: Mapped[str] = mapped_column(String(64))
    prompt_tokens: Mapped[int] = mapped_column(Integer, default=0)
    completion_tokens: Mapped[int] = mapped_column(Integer, default=0)
    total_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    response_time_ms: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    # "like" | "dislike" | null (no feedback given). Calling the feedback
    # endpoint is entirely optional for any bot consumer - this column just
    # stays null forever for a caller that never uses it.
    feedback: Mapped[str | None] = mapped_column(String(16), nullable=True)


class ChatFeedbackComment(Base):
    """Optional free-text reason attached to a dislike (bot-ui's "Learning
    loop" feature) - kept in its own table, not a new column on ChatLog,
    since this app's table-creation only ever creates NEW tables at startup
    (Base.metadata.create_all()) and never ALTERs an existing one. A new
    table needs no manual migration; a new column on chat_logs would.

    One comment per chat log (unique chat_log_id) - a user can update it by
    submitting again, not accumulate a thread of comments; this is meant to
    capture "what went wrong" once, not be a discussion."""

    __tablename__ = "chat_feedback_comments"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    chat_log_id: Mapped[int] = mapped_column(BigInteger, index=True, unique=True)
    comment: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class UsageLog(Base):
    """One row per billable AI call (chat OR embedding). Drives cost dashboards.
    Kept separate from ChatLog so embedding/ingestion cost is tracked too.
    """

    __tablename__ = "usage_logs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    bot_id: Mapped[str] = mapped_column(String(64), index=True)
    user_id: Mapped[str | None] = mapped_column(String(128), index=True, nullable=True)
    kind: Mapped[str] = mapped_column(String(16))                  # "chat" | "embedding"
    model: Mapped[str] = mapped_column(String(64), index=True)
    prompt_tokens: Mapped[int] = mapped_column(Integer, default=0)
    completion_tokens: Mapped[int] = mapped_column(Integer, default=0)
    total_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class SyncState(Base):
    """Per-site-per-library SharePoint delta token + last-run info
    (incremental sync).

    A bot can now pull from more than one SharePoint site (app/bots/schema.py
    SharePointConfig.sites), and library names are only unique WITHIN a site -
    two different sites can each have a library literally named "Documents" -
    so the row key has to be (bot_id, site_url, library), not just
    (bot_id, library), or two same-named libraries on different sites would
    collide and corrupt each other's delta tokens.

    The unique constraint closes a TOCTOU race in sync_job._get_state(): two
    concurrent sync triggers for the same bot (e.g. a manual "Sync Now" and
    the cron scheduler firing at the same time) could both SELECT, find no
    row, and both INSERT before either committed - producing two rows for
    the same (bot_id, site_url, library) that future lookups would pick
    between arbitrarily. The DB now rejects the second insert outright, and
    _get_state() catches that and re-reads the row the other transaction
    created instead."""

    __tablename__ = "sync_state"
    __table_args__ = (UniqueConstraint("bot_id", "site_url", "library", name="uq_sync_state_bot_site_library"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    bot_id: Mapped[str] = mapped_column(String(64), index=True)
    site_url: Mapped[str] = mapped_column(String(512), default="")
    library: Mapped[str] = mapped_column(String(256))
    delta_token: Mapped[str | None] = mapped_column(Text, nullable=True)
    index_version: Mapped[int] = mapped_column(Integer, default=1)  # bump to flush cache
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_status: Mapped[str | None] = mapped_column(String(32), nullable=True)


class EventLog(Base):
    """Errors and notable events, queryable by the admin Logs dashboard.
    type: error | sync | auth | ai | indexing
    """

    __tablename__ = "event_logs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    type: Mapped[str] = mapped_column(String(16), index=True)
    bot_id: Mapped[str | None] = mapped_column(String(64), index=True, nullable=True)
    message: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ListTable(Base):
    """Registry of the structured Postgres table backing one SharePoint List
    for a content_type=list bot (Option A - dual storage: rows are embedded
    into Qdrant AS TODAY for semantic search, AND written here as real typed
    columns so exact counts/filters/joins are possible - similarity search
    alone can only ever return a fuzzy top-k, never an exhaustive answer).

    Keyed by (bot_id, list_id) - list_id is the STABLE Graph list id, not the
    display name, so a list renamed on the real SharePoint site (this
    happened mid-session on the real tenant used to build this feature)
    keeps its same table; only list_name gets updated.

    This is the source of truth reconcile_list_tables() diffs against the
    bot's current YAML-declared lists: a list is "new" if it has no row
    here, "removed" if it has a row here but is no longer declared."""

    __tablename__ = "list_tables"
    __table_args__ = (UniqueConstraint("bot_id", "list_id", name="uq_list_tables_bot_list"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    bot_id: Mapped[str] = mapped_column(String(64), index=True)
    list_id: Mapped[str] = mapped_column(String(128))
    list_name: Mapped[str] = mapped_column(String(256))
    table_name: Mapped[str] = mapped_column(String(63))
    column_map: Mapped[dict] = mapped_column(JSONB)   # {sharepoint_field_name: sql_column_name}
    row_count: Mapped[int] = mapped_column(Integer, default=0)
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class WebSource(Base):
    """Registry of currently-indexed sources for a content_type=web bot -
    mirrors ListTable's role for list bots (app/db/list_tables.py), but
    there's no per-source Postgres table here, just this one row per
    SharePoint URL-list row that was successfully indexed into the bot's
    Qdrant collection. run_web_sync (app/workers/web_sync.py) diffs this
    against each sync's freshly-read enabled-source set to reconcile: a
    source disabled or deleted from the SharePoint list has its row here
    (and its Qdrant chunks) dropped on the next sync."""

    __tablename__ = "web_sources"
    __table_args__ = (UniqueConstraint("bot_id", "source_id", name="uq_web_sources_bot_source"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    bot_id: Mapped[str] = mapped_column(String(64), index=True)
    source_id: Mapped[str] = mapped_column(String(128))
    url: Mapped[str] = mapped_column(Text)
    category: Mapped[str | None] = mapped_column(String(128), nullable=True)
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Bot(Base):
    """Optional DB copy of bot metadata (source of truth stays in YAML for now)."""

    __tablename__ = "bots"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(128))
    enabled: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
