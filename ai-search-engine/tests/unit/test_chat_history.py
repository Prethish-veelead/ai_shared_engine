"""Pure-logic unit tests for temporary, non-persisted chat history
(app/rag/history.py, docs/CHAT_SESSIONS.md) - no real database, no live LLM.

Covers: the sliding-window trim, the [system, *history, user] message shape
both answer paths build from, that an empty/absent history reproduces
today's exact message shape (the core regression requirement), that the
vector path's RagPipeline.answer() only ever embeds the current question
(never history) while still forwarding history to the LLM, and that no
tool-shaped message can ever reach the structured path's history (verified
at the API boundary: AskRequest.HistoryTurn only ever has role/content).
"""
import pytest

from app.api.routes.ask import HistoryTurn
from app.bots.schema import (
    BotConfig,
    IndexingConfig,
    PromptConfig,
    SharePointConfig,
    VectorStoreConfig,
)
from app.llm.base import ChatResult, EmbedResult, LLMClient, ToolChatResult
from app.rag.history import build_messages, trim_history
from app.rag.pipeline import RagPipeline
from app.vectorstore.base import SearchHit, VectorStore


# ---- trim_history ----

def test_trim_history_none_is_empty():
    assert trim_history(None, 8) == []


def test_trim_history_empty_is_empty():
    assert trim_history([], 8) == []


def test_trim_history_max_zero_disables_history():
    history = [{"role": "user", "content": "hi"}]
    assert trim_history(history, 0) == []


def test_trim_history_negative_disables_history():
    history = [{"role": "user", "content": "hi"}]
    assert trim_history(history, -1) == []


def test_trim_history_keeps_last_n():
    history = [{"role": "user", "content": str(i)} for i in range(20)]
    trimmed = trim_history(history, 8)
    assert len(trimmed) == 8
    assert [m["content"] for m in trimmed] == [str(i) for i in range(12, 20)]


def test_trim_history_shorter_than_cap_is_unchanged():
    history = [{"role": "user", "content": "only one"}]
    assert trim_history(history, 8) == history


def test_trim_history_does_not_mutate_input():
    history = [{"role": "user", "content": str(i)} for i in range(20)]
    original = list(history)
    trim_history(history, 8)
    assert history == original


# ---- build_messages ----

def test_build_messages_empty_history_matches_pre_feature_shape():
    # This IS the regression requirement: an empty/absent history must
    # reproduce exactly the two-message [system, user] shape every answer
    # path built before this feature existed.
    messages = build_messages("sys prompt", [], "what is the leave policy?")
    assert messages == [
        {"role": "system", "content": "sys prompt"},
        {"role": "user", "content": "what is the leave policy?"},
    ]


def test_build_messages_none_history_same_as_empty():
    assert build_messages("sys", None, "q") == build_messages("sys", [], "q")


def test_build_messages_splices_history_between_system_and_user():
    history = [
        {"role": "user", "content": "who is EMP00050?"},
        {"role": "assistant", "content": "Rahul Muthu, Finance."},
    ]
    messages = build_messages("sys prompt", history, "what assets does he have?")
    assert messages == [
        {"role": "system", "content": "sys prompt"},
        {"role": "user", "content": "who is EMP00050?"},
        {"role": "assistant", "content": "Rahul Muthu, Finance."},
        {"role": "user", "content": "what assets does he have?"},
    ]


def test_build_messages_never_contains_tool_shaped_entries():
    history = [
        {"role": "user", "content": "q1"},
        {"role": "assistant", "content": "a1"},
    ]
    messages = build_messages("sys", history, "q2")
    for m in messages:
        assert m["role"] in ("system", "user", "assistant")
        assert "tool_calls" not in m
        assert m["role"] != "tool"


# ---- HistoryTurn (API boundary) - malformed/malicious history can't smuggle tool internals ----

def test_history_turn_drops_unknown_fields():
    # A client (malicious or buggy) trying to hand back a prior turn's raw
    # tool_calls/tool_call_id alongside role/content - HistoryTurn only ever
    # declares role+content, so anything else is dropped at the boundary,
    # before it could ever reach build_messages().
    turn = HistoryTurn(role="assistant", content="the answer", tool_calls=[{"id": "x"}], extra="junk")
    dumped = turn.model_dump()
    assert set(dumped.keys()) == {"role", "content"}


def test_history_turn_rejects_bad_role():
    with pytest.raises(Exception):
        HistoryTurn(role="tool", content="sneaky tool result")


# ---- RagPipeline.answer(): retrieval uses only the current question, history reaches the LLM ----

class _FakeVectorStore(VectorStore):
    def __init__(self):
        self.search_calls = []

    def ensure_collection(self, name, vector_size): ...
    def upsert(self, collection, points): ...
    def delete_by_doc(self, collection, doc_id): ...
    def delete_stale(self, collection, field, value, keep_ids): ...
    def delete_collection(self, collection): ...
    def index_stats(self, collection): return {"chunks": 0, "documents": 0}

    def search(self, collection, query_vector, top_k=5):
        self.search_calls.append((collection, query_vector, top_k))
        return [SearchHit(id="1", score=0.9, payload={"source": "doc", "text": "some content"})]


class _FakeLLMClient(LLMClient):
    def __init__(self):
        self.embed_calls = []
        self.chat_calls = []

    def chat(self, system, user, model, temperature=0.2, json_mode=False, history=None):
        self.chat_calls.append({"system": system, "user": user, "history": history})
        return ChatResult(text="an answer", prompt_tokens=10, completion_tokens=5, model=model)

    def chat_with_tools(self, messages, model, tools, temperature=0.2):
        return ToolChatResult(content="unused", tool_calls=[], prompt_tokens=0,
                              completion_tokens=0, model=model, assistant_message={})

    def embed(self, texts, model, is_query=False):
        self.embed_calls.append(list(texts))
        return EmbedResult(vectors=[[0.1, 0.2]], total_tokens=0, model=model)


def _library_bot() -> BotConfig:
    return BotConfig(
        id="test_lib", name="Test", route="/ask/test_lib",
        content_type="library",
        sharepoint=SharePointConfig(tenant="t", sites=[]),
        vectorstore=VectorStoreConfig(collection="test_col"),
        prompt=PromptConfig(system="You are a test bot."),
        indexing=IndexingConfig(),
    )


def test_pipeline_retrieval_embeds_only_current_question_not_history():
    store, llm = _FakeVectorStore(), _FakeLLMClient()
    pipeline = RagPipeline(store, llm)
    history = [
        {"role": "user", "content": "earlier unrelated question"},
        {"role": "assistant", "content": "earlier unrelated answer"},
    ]
    pipeline.answer(_library_bot(), "the current question", db=None, history=history)

    assert len(llm.embed_calls) == 1
    embedded_texts = llm.embed_calls[0]
    assert embedded_texts == ["the current question"]
    for text in embedded_texts:
        assert "earlier unrelated" not in text


def test_pipeline_forwards_trimmed_history_to_the_llm():
    store, llm = _FakeVectorStore(), _FakeLLMClient()
    pipeline = RagPipeline(store, llm)
    history = [{"role": "user", "content": "q1"}, {"role": "assistant", "content": "a1"}]
    pipeline.answer(_library_bot(), "q2", db=None, history=history)

    assert len(llm.chat_calls) == 1
    assert llm.chat_calls[0]["history"] == history


def test_pipeline_empty_history_forwards_empty_list_not_none_crash():
    store, llm = _FakeVectorStore(), _FakeLLMClient()
    pipeline = RagPipeline(store, llm)
    pipeline.answer(_library_bot(), "q", db=None, history=None)

    assert llm.chat_calls[0]["history"] == []


def test_pipeline_long_history_is_trimmed_before_reaching_the_llm():
    store, llm = _FakeVectorStore(), _FakeLLMClient()
    pipeline = RagPipeline(store, llm)
    long_history = [{"role": "user", "content": str(i)} for i in range(50)]
    pipeline.answer(_library_bot(), "q", db=None, history=long_history)

    sent_history = llm.chat_calls[0]["history"]
    from app.core.config import get_settings
    assert len(sent_history) == get_settings().chat_history_max_messages


# ---- answer_structured(): history splice with no tool-call replay ----

class _EmptyScalarsResult:
    def scalars(self):
        return self

    def all(self):
        return []


class _FakeDbNoRegisteredLists:
    """Just enough of Session.execute() for build_catalog() to see a bot
    with zero registered list_tables rows - an empty catalog, so
    answer_structured() never needs a real Postgres connection."""

    def execute(self, *args, **kwargs):
        return _EmptyScalarsResult()


class _FakeToolLLMClient(LLMClient):
    """chat_with_tools() records the exact messages it was called with, then
    immediately returns a final answer (no tool_calls) so the orchestrator's
    loop terminates after round 1 - lets the test inspect precisely what
    this turn's first LLM call was given."""

    def __init__(self):
        self.calls = []

    def chat(self, system, user, model, temperature=0.2, json_mode=False, history=None):
        raise AssertionError("answer_structured should call chat_with_tools, not chat")

    def chat_with_tools(self, messages, model, tools, temperature=0.2):
        self.calls.append(messages)
        return ToolChatResult(content="final answer", tool_calls=[], prompt_tokens=1,
                              completion_tokens=1, model=model, assistant_message={})

    def embed(self, texts, model, is_query=False):
        return EmbedResult(vectors=[[0.1]], total_tokens=0, model=model)


def _list_bot() -> BotConfig:
    return BotConfig(
        id="test_list", name="Test List Bot", route="/ask/test_list",
        content_type="list", structured_store=True,
        sharepoint=SharePointConfig(tenant="t", sites=[]),
        vectorstore=VectorStoreConfig(collection="test_list_col"),
        prompt=PromptConfig(system="You are a test list bot."),
        indexing=IndexingConfig(),
    )


def test_answer_structured_splices_history_with_no_tool_replay():
    from app.rag.structured.orchestrator import answer_structured

    llm = _FakeToolLLMClient()
    history = [
        {"role": "user", "content": "Give me EMP00050's details"},
        {"role": "assistant", "content": "Rahul Muthu, Finance Manager."},
    ]
    answer_structured(
        _list_bot(), "what assets does he have?", db=_FakeDbNoRegisteredLists(),
        vector_store=_FakeVectorStore(), llm=llm, history=history,
    )

    assert len(llm.calls) == 1
    messages = llm.calls[0]

    # No history turn, and no message built for this turn, is ever tool-shaped.
    for m in messages:
        assert m["role"] in ("system", "user", "assistant")
        assert "tool_calls" not in m

    # system, then the two history turns verbatim, then the current question.
    assert messages[0]["role"] == "system"
    assert messages[1] == history[0]
    assert messages[2] == history[1]
    assert messages[3] == {"role": "user", "content": "what assets does he have?"}
    assert len(messages) == 4
