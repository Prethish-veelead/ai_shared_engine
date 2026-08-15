"""Schema validation for content_type='chat' bots (app/bots/schema.py) - the
"no data source at all" content type. Pure Pydantic validation, no I/O.
"""
import pytest

from app.bots.schema import BotConfig


def _kwargs(**overrides):
    base = dict(
        id="classifier", name="Classifier", route="/ask/classifier", content_type="chat",
        vectorstore={},
        prompt={"system": "You classify tickets into Hardware/Software/Network."},
    )
    base.update(overrides)
    return base


def test_valid_chat_bot_loads():
    bot = BotConfig(**_kwargs())
    assert bot.content_type == "chat"
    assert bot.sharepoint is None
    assert bot.web is None
    assert bot.list_plus_library is None
    assert bot.vectorstore.collection is None
    assert bot.vectorstore.library_collection is None
    assert bot.vectorstore.list_collection is None


def test_chat_bot_with_response_fields_and_sample_questions():
    bot = BotConfig(**_kwargs(
        response_fields=[{"name": "confidence", "prompt": "How sure are you?"}],
        sample_questions=["Which category is a broken keyboard?"],
    ))
    assert bot.response_fields[0].name == "confidence"
    assert bot.sample_questions == ["Which category is a broken keyboard?"]


def test_chat_bot_with_sharepoint_block_rejected():
    kwargs = _kwargs(sharepoint={"tenant": "acme", "sites": [{"site_url": "https://x", "libraries": ["Docs"]}]})
    with pytest.raises(ValueError, match="no data source"):
        BotConfig(**kwargs)


def test_chat_bot_with_web_block_rejected():
    kwargs = _kwargs(web={"tenant": "acme", "site_url": "https://x", "source_list": "News"})
    with pytest.raises(ValueError, match="no data source"):
        BotConfig(**kwargs)


def test_chat_bot_with_list_plus_library_block_rejected():
    kwargs = _kwargs(list_plus_library={
        "tenant": "acme",
        "library_sites": [{"site_url": "https://x", "libraries": ["KB"]}],
        "list_sites": [{"site_url": "https://x", "lists": ["Tickets"]}],
    })
    with pytest.raises(ValueError, match="no data source"):
        BotConfig(**kwargs)


def test_chat_bot_with_collection_rejected():
    kwargs = _kwargs(vectorstore={"collection": "some_col"})
    with pytest.raises(ValueError, match="no Qdrant collection"):
        BotConfig(**kwargs)


def test_chat_bot_with_library_collection_rejected():
    kwargs = _kwargs(vectorstore={"library_collection": "lib_col"})
    with pytest.raises(ValueError, match="no Qdrant collection"):
        BotConfig(**kwargs)
