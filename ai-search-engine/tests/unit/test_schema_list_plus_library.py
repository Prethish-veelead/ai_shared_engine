"""Schema validation for content_type='list+library' bots (app/bots/schema.py)
- the two-collection VectorStoreConfig split, _valid_content_source's
list+library branch, and the library/list name-collision guard in
ListPlusLibraryConfig._valid_sites. Pure Pydantic validation, no I/O.
"""
import pytest

from app.bots.schema import BotConfig


def _kwargs(**overrides):
    base = dict(
        id="helpdesk", name="Helpdesk", route="/ask/helpdesk", content_type="list+library",
        list_plus_library={
            "tenant": "acme",
            "library_sites": [{"site_url": "https://acme.sharepoint.com/sites/helpdesk", "libraries": ["KB"]}],
            "list_sites": [{"site_url": "https://acme.sharepoint.com/sites/helpdesk", "lists": ["Resolved Tickets"]}],
        },
        vectorstore={"library_collection": "helpdesk_kb", "list_collection": "helpdesk_tickets"},
        prompt={"system": "Answer from the KB and resolved tickets only; cite each source."},
    )
    base.update(overrides)
    return base


def test_valid_list_plus_library_bot_loads():
    bot = BotConfig(**_kwargs())
    assert bot.content_type == "list+library"
    assert bot.sharepoint is None
    assert bot.web is None
    assert bot.vectorstore.collection is None
    assert bot.vectorstore.library_collection == "helpdesk_kb"
    assert bot.vectorstore.list_collection == "helpdesk_tickets"
    # Defaults
    assert bot.list_plus_library.solved_status_column == "Status"
    assert bot.list_plus_library.solved_status_value == "Solved"
    assert bot.list_plus_library.source_weights.library == 1.0
    assert bot.list_plus_library.source_weights.list == 1.0


def test_missing_list_plus_library_block_rejected():
    with pytest.raises(ValueError, match="no 'list_plus_library' config block"):
        BotConfig(**_kwargs(list_plus_library=None))


def test_sharepoint_alongside_list_plus_library_rejected():
    with pytest.raises(ValueError, match="not 'sharepoint'"):
        BotConfig(**_kwargs(sharepoint={
            "tenant": "acme", "sites": [{"site_url": "https://x", "libraries": ["Docs"]}],
        }))


def test_web_alongside_list_plus_library_rejected():
    with pytest.raises(ValueError, match="cannot have a 'web' config block"):
        BotConfig(**_kwargs(web={
            "tenant": "acme", "site_url": "https://x", "source_list": "News",
        }))


def test_missing_library_sites_rejected():
    kwargs = _kwargs()
    kwargs["list_plus_library"] = {**kwargs["list_plus_library"], "library_sites": []}
    with pytest.raises(ValueError, match="at least one library_sites"):
        BotConfig(**kwargs)


def test_missing_list_sites_rejected():
    kwargs = _kwargs()
    kwargs["list_plus_library"] = {**kwargs["list_plus_library"], "list_sites": []}
    with pytest.raises(ValueError, match="at least one list_sites"):
        BotConfig(**kwargs)


def test_library_sites_with_lists_rejected():
    kwargs = _kwargs()
    kwargs["list_plus_library"] = {
        **kwargs["list_plus_library"],
        "library_sites": [{"site_url": "https://x", "libraries": ["KB"], "lists": ["Oops"]}],
    }
    with pytest.raises(ValueError, match="only 'libraries' are valid here"):
        BotConfig(**kwargs)


def test_list_sites_with_libraries_rejected():
    kwargs = _kwargs()
    kwargs["list_plus_library"] = {
        **kwargs["list_plus_library"],
        "list_sites": [{"site_url": "https://x", "lists": ["Tickets"], "libraries": ["Oops"]}],
    }
    with pytest.raises(ValueError, match="only 'lists' are valid here"):
        BotConfig(**kwargs)


def test_library_and_list_name_collision_on_same_site_rejected():
    kwargs = _kwargs()
    kwargs["list_plus_library"] = {
        **kwargs["list_plus_library"],
        "library_sites": [{"site_url": "https://x", "libraries": ["Shared"]}],
        "list_sites": [{"site_url": "https://x", "lists": ["Shared"]}],
    }
    with pytest.raises(ValueError, match="used as both a library and a list"):
        BotConfig(**kwargs)


def test_same_name_different_site_is_not_a_collision():
    kwargs = _kwargs()
    kwargs["list_plus_library"] = {
        **kwargs["list_plus_library"],
        "library_sites": [{"site_url": "https://a", "libraries": ["Shared"]}],
        "list_sites": [{"site_url": "https://b", "lists": ["Shared"]}],
    }
    bot = BotConfig(**kwargs)   # should not raise
    assert bot.content_type == "list+library"


# ---- vectorstore split ----

def test_plain_collection_instead_of_split_rejected():
    # library_collection/list_collection both set correctly, but 'collection'
    # ALSO set - isolates the "collection must be unset" check specifically,
    # separate from the "library/list_collection must be set" check below.
    kwargs = _kwargs(vectorstore={
        "collection": "one_shared_collection",
        "library_collection": "helpdesk_kb", "list_collection": "helpdesk_tickets",
    })
    with pytest.raises(ValueError, match="not 'collection'"):
        BotConfig(**kwargs)


def test_missing_library_collection_rejected():
    kwargs = _kwargs(vectorstore={"list_collection": "helpdesk_tickets"})
    with pytest.raises(ValueError, match="requires both"):
        BotConfig(**kwargs)


def test_missing_list_collection_rejected():
    kwargs = _kwargs(vectorstore={"library_collection": "helpdesk_kb"})
    with pytest.raises(ValueError, match="requires both"):
        BotConfig(**kwargs)


def test_identical_library_and_list_collection_rejected():
    kwargs = _kwargs(vectorstore={"library_collection": "same", "list_collection": "same"})
    with pytest.raises(ValueError, match="must be different Qdrant collections"):
        BotConfig(**kwargs)


# ---- regression: single-source bots still require vectorstore.collection ----

def test_library_bot_without_collection_rejected():
    with pytest.raises(ValueError, match="requires 'vectorstore.collection'"):
        BotConfig(
            id="hr", name="HR", route="/ask/hr", content_type="library",
            sharepoint={"tenant": "acme", "sites": [{"site_url": "https://x", "libraries": ["Docs"]}]},
            vectorstore={},
            prompt={"system": "Answer from HR docs."},
        )


def test_web_bot_without_collection_rejected():
    with pytest.raises(ValueError, match="requires 'vectorstore.collection'"):
        BotConfig(
            id="news", name="News", route="/ask/news", content_type="web",
            web={"tenant": "acme", "site_url": "https://x", "source_list": "News"},
            vectorstore={},
            prompt={"system": "Answer from news."},
        )


def test_library_bot_with_collection_still_works():
    bot = BotConfig(
        id="hr", name="HR", route="/ask/hr", content_type="library",
        sharepoint={"tenant": "acme", "sites": [{"site_url": "https://x", "libraries": ["Docs"]}]},
        vectorstore={"collection": "hr_col"},
        prompt={"system": "Answer from HR docs."},
    )
    assert bot.vectorstore.collection == "hr_col"
