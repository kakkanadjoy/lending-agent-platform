"""Model loading for retrieval — the embedding bi-encoder and the cross-encoder
reranker. Both are small, both run locally on CPU.

Models are loaded lazily and cached: the first call pays the load cost (and,
on a fresh machine, the one-time download), every later call reuses the loaded
model. Keeping this in its own module means the rest of the code asks for an
embedding or a rerank score without caring how the model gets there.
"""
from __future__ import annotations

import functools

EMBED_MODEL = "all-MiniLM-L6-v2"                          # ~80MB, 384-dim
RERANK_MODEL = "cross-encoder/ms-marco-MiniLM-L6-v2"      # ~80MB


@functools.lru_cache(maxsize=1)
def _embedder():
    import torch
    from sentence_transformers import SentenceTransformer
    original_to = torch.nn.Module.to
    def safe_to(self, *args, **kwargs):
        try:
            return original_to(self, *args, **kwargs)
        except NotImplementedError:
            return self
    torch.nn.Module.to = safe_to
    model = SentenceTransformer(EMBED_MODEL)
    torch.nn.Module.to = original_to
    return model

@functools.lru_cache(maxsize=1)
def _reranker():
    import torch
    from sentence_transformers import CrossEncoder
    original_to = torch.nn.Module.to
    def safe_to(self, *args, **kwargs):
        try:
            return original_to(self, *args, **kwargs)
        except NotImplementedError:
            return self
    torch.nn.Module.to = safe_to
    model = CrossEncoder(RERANK_MODEL)
    torch.nn.Module.to = original_to
    return model

def embed_one(text: str) -> list[float]:
    """A single text -> its embedding vector (as a plain list for psycopg)."""
    return _embedder().encode(text, normalize_embeddings=True).tolist()


def rerank(query: str, candidates: list[str]) -> list[float]:
    """Score each candidate against the query with the cross-encoder. Higher is
    more relevant. The reranker reads query and candidate together, which is
    why it's more accurate than comparing independent embeddings."""
    if not candidates:
        return []
    pairs = [(query, c) for c in candidates]
    return [float(s) for s in _reranker().predict(pairs)]
