"""Unit tests for ListPlusLibraryConfig.retrieval_mode="sequential"
(app/rag/structured/sequential.py) - the list-first, library-on-fallback
control flow. Same lightweight fake-LLM/fake-DB pattern as
test_chat_history.py's test_answer_structured_splices_history_with_no_tool_replay
(no live DB, no live LLM). No tool_calls are exercised here - the actual
semantic_search/weighted_merge_retrieve mechanics are already covered by
test_combined_retrieval.py; these tests cover only the NEW two-phase
sentinel-detection control flow (does phase B run or not, does the sentinel
ever leak to the user, does merge mode still bypass all of this).
"""
from app.bots.schema import (
    BotConfig,
    IndexingConfig,
    ListPlusLibraryConfig,
    PromptConfig,
    SharePointConfig,
    SharePointSite,
    VectorStoreConfig,
)
from app.llm.base import EmbedResult, LLMClient, ToolChatResult
from app.rag.combined import answer_combined
from app.rag.structured.orchestrator import answer_structured
from app.rag.structured.sequential import LIST_NOT_FOUND_SENTINEL
from app.vectorstore.base import VectorStore


class _EmptyScalarsResult:
    def scalars(self):
        return self

    def all(self):
        return []


class _FakeDbNoRegisteredLists:
    """Just enough of Session.execute() for build_catalog() to see a bot with
    zero registered list_tables rows - an empty catalog, so these tests never
    need a real Postgres connection."""

    def execute(self, *args, **kwargs):
        return _EmptyScalarsResult()


class _FakeVectorStore(VectorStore):
    """No tool call ever reaches semantic_search in these tests (every
    scripted LLM response returns tool_calls=[]), so .search() should never
    be called - asserting that loudly rather than silently returning []."""

    def ensure_collection(self, name, vector_size): ...
    def upsert(self, collection, points): ...
    def delete_by_doc(self, collection, doc_id): ...
    def delete_stale(self, collection, field, value, keep_ids): ...
    def delete_collection(self, collection): ...
    def index_stats(self, collection):
        return {"chunks": 0, "documents": 0}

    def search(self, collection, query_vector, top_k=5):
        raise AssertionError("no tool call should reach vector_store.search in these tests")


class _ScriptedToolLLMClient(LLMClient):
    """Returns one scripted content string per chat_with_tools() call, always
    with tool_calls=[] (so each call's round terminates immediately) - lets a
    test script exactly what the list-only phase and library-unlocked phase
    "say" without any real tool execution."""

    def __init__(self, contents: list[str]):
        self._contents = list(contents)
        self.calls: list[list[dict]] = []

    def chat(self, system, user, model, temperature=0.2, json_mode=False, history=None):
        raise AssertionError("sequential mode should call chat_with_tools, not chat")

    def chat_with_tools(self, messages, model, tools, temperature=0.2):
        content = self._contents[len(self.calls)]
        self.calls.append([dict(m) for m in messages])
        return ToolChatResult(content=content, tool_calls=[], prompt_tokens=1,
                              completion_tokens=1, model=model, assistant_message={})

    def embed(self, texts, model, is_query=False):
        return EmbedResult(vectors=[[0.1]], total_tokens=0, model=model)


def _list_bot() -> BotConfig:
    # Stands in for app/rag/combined.py's SimpleNamespace shim -
    # answer_structured/run_sequential only ever read the handful of
    # attributes off `bot` that a real BotConfig has too (id,
    # vectorstore.collection, prompt, models, response_fields).
    return BotConfig(
        id="test_seq", name="Test Sequential Bot", route="/ask/test_seq",
        content_type="list", structured_store=True,
        sharepoint=SharePointConfig(tenant="t", sites=[]),
        vectorstore=VectorStoreConfig(collection="test_list_col"),
        prompt=PromptConfig(system="You are a test bot."),
        indexing=IndexingConfig(),
    )


# ---- answer_structured(retrieval_mode="sequential") ----

def test_sequential_list_answers_immediately_library_never_queried():
    llm = _ScriptedToolLLMClient(["The printer jam was already fixed in ticket #42."])
    response = answer_structured(
        _list_bot(), "how do I fix the printer jam?",
        db=_FakeDbNoRegisteredLists(), vector_store=_FakeVectorStore(), llm=llm,
        secondary_collection="lib_col", retrieval_mode="sequential",
    )
    assert len(llm.calls) == 1   # phase B never ran
    assert response.answer == "The printer jam was already fixed in ticket #42."


def test_sequential_list_no_answer_falls_back_to_library():
    llm = _ScriptedToolLLMClient([LIST_NOT_FOUND_SENTINEL, "Per the KB, restart the printer service."])
    response = answer_structured(
        _list_bot(), "how do I fix the printer jam?",
        db=_FakeDbNoRegisteredLists(), vector_store=_FakeVectorStore(), llm=llm,
        secondary_collection="lib_col", retrieval_mode="sequential",
    )
    assert len(llm.calls) == 2
    assert response.answer == "Per the KB, restart the printer service."
    assert LIST_NOT_FOUND_SENTINEL not in response.answer

    # Phase B continues the SAME conversation (phase A's system+question are
    # still there) with one appended "library unlocked" turn - not a reset.
    phase_a_messages, phase_b_messages = llm.calls
    assert phase_b_messages[:len(phase_a_messages)] == phase_a_messages
    assert phase_b_messages[-1]["role"] == "user"
    assert "now also available" in phase_b_messages[-1]["content"]


def test_sequential_neither_side_answers_returns_i_dont_know():
    llm = _ScriptedToolLLMClient([LIST_NOT_FOUND_SENTINEL, LIST_NOT_FOUND_SENTINEL])
    response = answer_structured(
        _list_bot(), "some totally uncovered question",
        db=_FakeDbNoRegisteredLists(), vector_store=_FakeVectorStore(), llm=llm,
        secondary_collection="lib_col", retrieval_mode="sequential",
    )
    assert len(llm.calls) == 2
    assert response.answer == "I don't know."
    assert response.citations == []


def test_sequential_phase_a_system_prompt_carries_the_list_only_instruction():
    llm = _ScriptedToolLLMClient(["answer"])
    answer_structured(
        _list_bot(), "q", db=_FakeDbNoRegisteredLists(), vector_store=_FakeVectorStore(), llm=llm,
        secondary_collection="lib_col", retrieval_mode="sequential",
    )
    system_message = llm.calls[0][0]
    assert system_message["role"] == "system"
    assert LIST_NOT_FOUND_SENTINEL in system_message["content"]


# ---- merge mode (default) must be completely unaffected ----

def test_merge_mode_default_does_not_dispatch_to_sequential():
    llm = _ScriptedToolLLMClient(["merged answer"])
    response = answer_structured(
        _list_bot(), "q", db=_FakeDbNoRegisteredLists(), vector_store=_FakeVectorStore(), llm=llm,
        secondary_collection="lib_col",   # retrieval_mode omitted -> defaults to "merge"
    )
    assert len(llm.calls) == 1
    assert LIST_NOT_FOUND_SENTINEL not in llm.calls[0][0]["content"]
    assert response.answer == "merged answer"


def test_merge_mode_explicit_also_bypasses_sequential():
    llm = _ScriptedToolLLMClient(["merged answer"])
    response = answer_structured(
        _list_bot(), "q", db=_FakeDbNoRegisteredLists(), vector_store=_FakeVectorStore(), llm=llm,
        secondary_collection="lib_col", retrieval_mode="merge",
    )
    assert len(llm.calls) == 1
    assert response.answer == "merged answer"


# ---- answer_combined() threads cfg.retrieval_mode through ----

def _combined_bot(retrieval_mode: str) -> BotConfig:
    return BotConfig(
        id="helpdesk", name="Helpdesk", route="/ask/helpdesk", content_type="list+library",
        list_plus_library=ListPlusLibraryConfig(
            tenant="acme",
            library_sites=[SharePointSite(site_url="https://acme.sharepoint.com/sites/helpdesk",
                                          libraries=["KB"])],
            list_sites=[SharePointSite(site_url="https://acme.sharepoint.com/sites/helpdesk",
                                       lists=["Resolved Tickets"])],
            retrieval_mode=retrieval_mode,
        ),
        vectorstore=VectorStoreConfig(library_collection="helpdesk_kb", list_collection="helpdesk_tickets"),
        prompt=PromptConfig(system="Answer from the KB and resolved tickets only."),
    )


def test_answer_combined_default_config_uses_merge_mode():
    llm = _ScriptedToolLLMClient(["merged answer"])
    response = answer_combined(
        _combined_bot("merge"), "q", db=_FakeDbNoRegisteredLists(),
        vector_store=_FakeVectorStore(), llm=llm,
    )
    assert len(llm.calls) == 1
    assert LIST_NOT_FOUND_SENTINEL not in llm.calls[0][0]["content"]
    assert response.answer == "merged answer"


def test_answer_combined_sequential_config_dispatches_to_sequential():
    llm = _ScriptedToolLLMClient(["The list already answers this."])
    response = answer_combined(
        _combined_bot("sequential"), "q", db=_FakeDbNoRegisteredLists(),
        vector_store=_FakeVectorStore(), llm=llm,
    )
    assert LIST_NOT_FOUND_SENTINEL in llm.calls[0][0]["content"]   # phase A's list-only instruction
    assert response.answer == "The list already answers this."
