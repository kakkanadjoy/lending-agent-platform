"""Hybrid retrieval over the policy corpus.

The pipeline, in stages:

    query
      -> lexical search   (postgres full-text, exact terms/jargon)
      -> semantic search  (pgvector, meaning even without shared words)
      -> Reciprocal Rank Fusion   (merge the two ranked lists into one)
      -> cross-encoder rerank      (read query+candidate together, sharpen)
      -> top-K

Lexical and semantic have opposite blind spots, so we run both: lexical nails
codes and defined terms, semantic catches paraphrases. RRF blends their
rankings without needing to reconcile their different score scales. The
cross-encoder then re-judges the small fused candidate set precisely.

`search()` is the seam: callers get ranked, cited chunks and never see the
machinery, so the internals can change without touching the agents.
"""
from __future__ import annotations

from dataclasses import dataclass

from db import repository as repo
from rag.embedding import embed_one, rerank

RRF_K = 60   # the standard RRF constant; dampens the influence of low ranks


@dataclass
class Hit:
    chunk_id: str
    code: str
    section: str
    title: str
    body: str
    score: float            # cross-encoder relevance (final ordering)
    found_by: str           # "lexical", "semantic", or "both" — for transparency


# def _lexical(conn, query: str, limit: int) -> list[str]:
#     """Top chunk_ids by postgres full-text rank. We compute the tsquery once
#     in a subquery and reuse it for both the match and the ranking — clearer,
#     and it sidesteps a psycopg quirk with the same function appearing twice."""
#     with conn.cursor() as cur:
#         cur.execute(
#             "SELECT chunk_id FROM policy_chunks, "
#             "plainto_tsquery('english', %s) AS q "
#             "WHERE tsv @@ q "
#             "ORDER BY ts_rank(tsv, q) DESC LIMIT %s",
#             (query, limit),
#         )
#         return [r["chunk_id"] for r in cur.fetchall()]

def _lexical(conn, query: str, limit: int) -> list[str]:
    """Top chunk_ids by postgres full-text rank. We OR the query terms (rather
    than plainto_tsquery's implicit AND) so a multi-word natural-language query
    matches sections sharing ANY salient term, ranked by overlap."""
    terms = [t for t in query.replace(",", " ").split() if t.isalnum()]
    if not terms:
        return []
    tsquery = " | ".join(terms)  # OR them together
    with conn.cursor() as cur:
        cur.execute(
            "SELECT chunk_id, ts_rank(tsv, to_tsquery('english', %(q)s)) AS rank "
            "FROM policy_chunks "
            "WHERE tsv @@ to_tsquery('english', %(q)s) "
            "ORDER BY rank DESC LIMIT %(lim)s",
            {"q": tsquery, "lim": limit},
        )
        return [r["chunk_id"] for r in cur.fetchall()]


def _semantic(conn, query: str, limit: int) -> list[str]:
    """Top chunk_ids by embedding cosine distance (<=> is pgvector's operator)."""
    qvec = embed_one(query)
    with conn.cursor() as cur:
        cur.execute(
            "SELECT chunk_id FROM policy_chunks "
            "ORDER BY embedding <=> %s::vector LIMIT %s",
            (str(qvec), limit),
        )
        return [r["chunk_id"] for r in cur.fetchall()]


def _rrf(lexical: list[str], semantic: list[str]) -> dict[str, float]:
    """Reciprocal Rank Fusion: each list contributes 1/(K+rank) per item.
    Items ranked highly by both lists rise; items in only one still count."""
    scores: dict[str, float] = {}
    for ranked in (lexical, semantic):
        for rank, chunk_id in enumerate(ranked):
            scores[chunk_id] = scores.get(chunk_id, 0.0) + 1.0 / (RRF_K + rank)
    return scores


def search(query: str, k: int = 3, candidate_pool: int = 10,
           url: str | None = None) -> list[Hit]:
    """Run the full pipeline and return the top-k cited chunks."""
    with repo.connect(url) as conn:
        lexical = _lexical(conn, query, candidate_pool)
        semantic = _semantic(conn, query, candidate_pool)
        fused = _rrf(lexical, semantic)
        if not fused:
            return []

        # Pull the fused candidates' full rows for reranking and return.
        ids = list(fused.keys())
        with conn.cursor() as cur:
            cur.execute("SELECT chunk_id, code, section, title, body "
                        "FROM policy_chunks WHERE chunk_id = ANY(%s)", (ids,))
            rows = {r["chunk_id"]: r for r in cur.fetchall()}

    # Cross-encoder rerank the fused candidates against the query.
    candidate_ids = list(rows.keys())
    scores = rerank(query, [rows[cid]["body"] for cid in candidate_ids])
    ranked = sorted(zip(candidate_ids, scores), key=lambda t: t[1], reverse=True)

    lex_set, sem_set = set(lexical), set(semantic)
    hits = []
    for cid, score in ranked[:k]:
        r = rows[cid]
        found_by = ("both" if cid in lex_set and cid in sem_set
                    else "lexical" if cid in lex_set else "semantic")
        hits.append(Hit(cid, r["code"], r["section"], r["title"], r["body"],
                        float(score), found_by))
    return hits
