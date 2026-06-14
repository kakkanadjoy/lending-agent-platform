"""RAG tests.

The RRF fusion is pure logic and tested without any model or database. The
retrieval-quality tests need the embedded corpus, so they ingest first, then
assert the pipeline finds the right policy section — including the key case:
semantic search finding a section from a paraphrase with no shared words.
"""
import pytest

from rag.search import _rrf, RRF_K


# ── fusion logic, no models/db ──────────────────────────────────────────────

def test_rrf_rewards_agreement():
    lexical = ["A", "B", "C"]
    semantic = ["B", "A", "D"]
    scores = _rrf(lexical, semantic)
    ranked = sorted(scores, key=scores.get, reverse=True)
    # A and B are in both lists; they must outrank the single-list C and D
    assert set(ranked[:2]) == {"A", "B"}
    assert scores["A"] == pytest.approx(1 / (RRF_K + 0) + 1 / (RRF_K + 1))
    assert scores["C"] == pytest.approx(1 / (RRF_K + 2))


def test_rrf_handles_empty_lists():
    assert _rrf([], []) == {}


# ── retrieval quality (needs the embedded corpus) ───────────────────────────
# These load the models; mark slow so they can be skipped in a fast loop.

@pytest.fixture(scope="module")
def ingested():
    pytest.importorskip("sentence_transformers")
    from rag import ingest
    ingest.ingest()
    return True


@pytest.mark.slow
def test_exact_term_query_finds_section(ingested):
    from rag.search import search
    hits = search("debt service coverage ratio minimum", k=3)
    assert hits
    assert any(h.code == "DSCR-MIN" for h in hits)
    # exact-term query should be caught lexically
    top = hits[0]
    assert top.section  # has a citable section


@pytest.mark.slow
def test_semantic_query_finds_section_without_shared_words(ingested):
    """The headline RAG moment: a paraphrase with no shared vocabulary still
    finds the right section, via the semantic half."""
    from rag.search import search
    hits = search("the borrower lied about how much money they make", k=3)
    assert hits
    assert any(h.code == "INCOME-MISREP" for h in hits)


@pytest.mark.slow
def test_every_rule_section_is_retrievable(ingested):
    """Single-source-of-truth check: every policy section the engine can cite
    actually exists in the corpus and can be retrieved by its own title."""
    from rag import corpus
    from rag.search import search
    for chunk in corpus.build_corpus():
        hits = search(chunk["title"], k=4)
        assert any(h.code == chunk["code"] for h in hits), chunk["code"]
