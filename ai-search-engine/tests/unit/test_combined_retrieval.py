"""Pure-logic unit tests for query_tools.weighted_merge_retrieve - the merge/
weight/de-dupe logic that makes list+library retrieval work (semantic_search
and the structured orchestrator's round-cap fallback both call this). No real
vector store or embedding call - a fake Retriever stands in, matching this
repo's existing style of injecting a plain fake object rather than a mocking
library (see test_web_fetcher.py's fake_get).
"""
from app.rag.structured.query_tools import weighted_merge_retrieve
from app.vectorstore.base import SearchHit


class _FakeRetriever:
    """Returns canned hits per collection name, and a fixed token count per
    call, so tests can assert both the merged hit order AND the summed
    embedding token count."""

    def __init__(self, hits_by_collection: dict[str, list[SearchHit]], tokens_per_call: int = 5):
        self._hits_by_collection = hits_by_collection
        self._tokens_per_call = tokens_per_call
        self.calls: list[str] = []

    def retrieve(self, *, collection, question, embedding_model, top_k):
        self.calls.append(collection)
        return self._hits_by_collection.get(collection, [])[:top_k], self._tokens_per_call


def _hit(id_, score, doc_id=None, **extra_payload):
    payload = {"doc_id": doc_id or id_, "source": id_, **extra_payload}
    return SearchHit(id=id_, score=score, payload=payload)


# ---- secondary_collection=None: today's exact single-collection behavior ----

def test_no_secondary_collection_returns_primary_hits_unchanged():
    retriever = _FakeRetriever({"list_col": [_hit("a", 0.9), _hit("b", 0.5)]})
    hits, tokens = weighted_merge_retrieve(
        retriever, primary_collection="list_col", secondary_collection=None,
        primary_weight=1.0, secondary_weight=1.0,
        question="q", embedding_model="m", top_k=5,
    )
    assert [h.id for h in hits] == ["a", "b"]
    assert tokens == 5   # only ONE retrieve() call - never touches a second collection
    assert retriever.calls == ["list_col"]


# ---- both sources always queried, never a sequential fallback ----

def test_both_collections_always_queried():
    retriever = _FakeRetriever({"list_col": [_hit("a", 0.9)], "lib_col": [_hit("b", 0.8)]})
    weighted_merge_retrieve(
        retriever, primary_collection="list_col", secondary_collection="lib_col",
        primary_weight=1.0, secondary_weight=1.0,
        question="q", embedding_model="m", top_k=5,
    )
    assert retriever.calls == ["list_col", "lib_col"]


def test_tokens_summed_across_both_collections():
    retriever = _FakeRetriever({"list_col": [_hit("a", 0.9)], "lib_col": [_hit("b", 0.8)]}, tokens_per_call=3)
    _, tokens = weighted_merge_retrieve(
        retriever, primary_collection="list_col", secondary_collection="lib_col",
        primary_weight=1.0, secondary_weight=1.0,
        question="q", embedding_model="m", top_k=5,
    )
    assert tokens == 6


# ---- unweighted merge: plain score-descending order across both sources ----

def test_unweighted_merge_orders_by_raw_score():
    retriever = _FakeRetriever({
        "list_col": [_hit("list-low", 0.4)],
        "lib_col": [_hit("lib-high", 0.9)],
    })
    hits, _ = weighted_merge_retrieve(
        retriever, primary_collection="list_col", secondary_collection="lib_col",
        primary_weight=1.0, secondary_weight=1.0,
        question="q", embedding_model="m", top_k=5,
    )
    assert [h.id for h in hits] == ["lib-high", "list-low"]


# ---- source_weights actually shift ranking, not just re-scale uniformly ----

def test_source_weight_can_flip_ranking():
    # Raw scores would rank list-side first (0.6 > 0.55), but a strong list
    # weight (2.0) vs a weak library weight (0.5) should flip that.
    retriever = _FakeRetriever({
        "list_col": [_hit("list-hit", 0.6)],
        "lib_col": [_hit("lib-hit", 0.55)],
    })
    hits, _ = weighted_merge_retrieve(
        retriever, primary_collection="list_col", secondary_collection="lib_col",
        primary_weight=1.0, secondary_weight=1.0,
        question="q", embedding_model="m", top_k=5,
    )
    assert [h.id for h in hits] == ["list-hit", "lib-hit"]   # unweighted: raw order

    hits, _ = weighted_merge_retrieve(
        retriever, primary_collection="list_col", secondary_collection="lib_col",
        primary_weight=0.5, secondary_weight=2.0,
        question="q", embedding_model="m", top_k=5,
    )
    assert [h.id for h in hits] == ["lib-hit", "list-hit"]   # weighted: library boosted, flips order


def test_source_weights_favoring_list_keep_library_results_present():
    # Skewing weight toward one source must never DROP the other's results
    # entirely - both sources are always represented if they have hits.
    retriever = _FakeRetriever({
        "list_col": [_hit("t1", 0.9), _hit("t2", 0.8)],
        "lib_col": [_hit("k1", 0.85)],
    })
    hits, _ = weighted_merge_retrieve(
        retriever, primary_collection="list_col", secondary_collection="lib_col",
        primary_weight=2.0, secondary_weight=1.0,
        question="q", embedding_model="m", top_k=5,
    )
    assert {h.id for h in hits} == {"t1", "t2", "k1"}


# ---- de-dupe by doc_id, keeping the higher-weighted occurrence ----

def test_dedupe_keeps_higher_weighted_score_occurrence():
    retriever = _FakeRetriever({
        "list_col": [_hit("from-list", 0.5, doc_id="shared-doc")],
        "lib_col": [_hit("from-lib", 0.9, doc_id="shared-doc")],
    })
    hits, _ = weighted_merge_retrieve(
        retriever, primary_collection="list_col", secondary_collection="lib_col",
        primary_weight=1.0, secondary_weight=1.0,
        question="q", embedding_model="m", top_k=5,
    )
    assert len(hits) == 1
    assert hits[0].id == "from-lib"   # 0.9 beats 0.5


# ---- top_k cap applies to the MERGED set, not each side independently ----

def test_top_k_caps_the_merged_set():
    retriever = _FakeRetriever({
        "list_col": [_hit("a", 0.9), _hit("b", 0.8)],
        "lib_col": [_hit("c", 0.7), _hit("d", 0.6)],
    })
    hits, _ = weighted_merge_retrieve(
        retriever, primary_collection="list_col", secondary_collection="lib_col",
        primary_weight=1.0, secondary_weight=1.0,
        question="q", embedding_model="m", top_k=2,
    )
    assert [h.id for h in hits] == ["a", "b"]
