"""
retrieval.py — Query interface for the NEU housing RAG system
-------------------------------------------------------------
Exposes a single public function:

    retrieve(query, top_k=5) -> list[dict]

Each returned dict contains:
    text       — the chunk text
    source     — human-readable document name
    url        — original URL
    chunk_index — 0-based position within that source document
    distance   — cosine distance (0 = identical, 2 = opposite)
    score      — 1 - distance, so higher = more relevant (for display)

ChromaDB API calls used
───────────────────────
chromadb.PersistentClient(path)
    Re-opens the on-disk database written by embed_and_store.py.

client.get_collection(name)
    Opens an *existing* collection; raises an error if it doesn't
    exist, which is intentional — it surfaces the problem clearly
    instead of silently returning an empty result set.

collection.query(query_embeddings, n_results, include)
    Runs approximate-nearest-neighbour search over the stored
    HNSW index.
    • query_embeddings  — list of one vector (shape [1, 384])
    • n_results         — k, number of neighbours to return
    • include           — controls which fields come back;
                          omitting "embeddings" saves bandwidth
                          since we don't need the raw vectors.
    Returns a dict whose values are lists-of-lists (one inner list
    per query vector), so we index [0] to get the single-query results.
"""

import chromadb
from sentence_transformers import SentenceTransformer

CHROMA_PATH = "./chroma_db"
COLLECTION  = "housing_chunks"
MODEL_NAME  = "all-MiniLM-L6-v2"

# Load once at import time so repeated calls to retrieve() don't reload the model
_model: SentenceTransformer | None = None


def _get_model() -> SentenceTransformer:
    global _model
    if _model is None:
        _model = SentenceTransformer(MODEL_NAME)
    return _model


def retrieve(query: str, top_k: int = 5) -> list[dict]:
    """
    Embed `query` and return the `top_k` most relevant chunks.

    Parameters
    ----------
    query  : natural-language question or search phrase
    top_k  : number of results to return (default 5, matching planning.md)

    Returns
    -------
    list of dicts, sorted by ascending cosine distance (most relevant first)
    """
    model = _get_model()
    query_vector = model.encode([query]).tolist()   # shape (1, 384) → list-of-lists

    client     = chromadb.PersistentClient(path=CHROMA_PATH)
    collection = client.get_collection(COLLECTION)

    results = collection.query(
        query_embeddings = query_vector,
        n_results        = top_k,
        include          = ["documents", "metadatas", "distances"],
    )

    # collection.query always returns lists-of-lists (one per query);
    # index [0] because we sent exactly one query vector.
    hits = []
    for doc, meta, dist in zip(
        results["documents"][0],
        results["metadatas"][0],
        results["distances"][0],
    ):
        hits.append({
            "text":        doc,
            "source":      meta["source"],
            "url":         meta["url"],
            "chunk_index": meta["chunk_index"],
            "distance":    round(dist, 4),
            "score":       round(1 - dist, 4),   # higher = more relevant
        })

    return hits


# ── CLI helper ─────────────────────────────────────────────────────────────────

def _print_results(query: str, hits: list[dict]) -> None:
    print(f"\n{'═' * 70}")
    print(f"Query : {query}")
    print(f"{'═' * 70}")
    for i, h in enumerate(hits, 1):
        print(f"\n  [{i}] score={h['score']:.4f}  dist={h['distance']:.4f}")
        print(f"      {h['source']}  (chunk {h['chunk_index']})")
        print(f"      {h['url']}")
        # Print up to 400 chars of the chunk text
        preview = h["text"].replace("\n", " ")
        print(f"\n      {preview[:400]}{'…' if len(preview) > 400 else ''}")


if __name__ == "__main__":
    # ── Evaluation plan queries (planning.md §Evaluation Plan) ────────────────
    # Q1: What housing search tool does Northeastern recommend?
    # Q2: What is a common off-campus housing strategy for co-op students?
    # Q3: What commute advice do students give?
    # Q4: What social media apps can students use for housing leads?
    # Q5: What do students say about broker fees near Northeastern?

    eval_queries = [
        "What housing search tool does Northeastern recommend?",
        "What is a common off-campus housing strategy for co-op students?",
        "What do students say about broker fees near Northeastern?",
    ]

    for q in eval_queries:
        hits = retrieve(q, top_k=5)
        _print_results(q, hits)
