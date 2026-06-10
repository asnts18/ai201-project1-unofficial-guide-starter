"""
embed_and_store.py — Embedding + ChromaDB ingestion (Milestone 4)
------------------------------------------------------------------
Reads chunks.json produced by chunk_documents.py, embeds every chunk
with all-MiniLM-L6-v2, and upserts the results into a persistent
ChromaDB collection.

ChromaDB API calls used
───────────────────────
chromadb.PersistentClient(path)
    Opens (or creates) an on-disk database at `path`.  All data
    survives between Python sessions.

client.get_or_create_collection(name, metadata)
    Returns the named collection, creating it if it doesn't exist.
    metadata={"hnsw:space": "cosine"} tells the HNSW index to use
    cosine distance so scores are comparable across queries.

collection.upsert(ids, embeddings, documents, metadatas)
    Insert-or-update in one call.  If a chunk id already exists the
    record is overwritten, so re-running this script is safe.
    • ids        — unique string identifier per chunk
    • embeddings — precomputed float vectors (list-of-lists)
    • documents  — raw chunk text, stored for later inspection
    • metadatas  — arbitrary key/value pairs; we store source name,
                   original URL, chunk index within its document, and
                   estimated token count for debugging
"""

import json
from pathlib import Path

import chromadb
from sentence_transformers import SentenceTransformer

CHUNKS_FILE = Path("chunks.json")
CHROMA_PATH = "./chroma_db"
COLLECTION  = "housing_chunks"
MODEL_NAME  = "all-MiniLM-L6-v2"


def run() -> None:
    # ── load chunks ───────────────────────────────────────────────────────────
    if not CHUNKS_FILE.exists():
        raise FileNotFoundError("chunks.json not found — run chunk_documents.py first.")

    chunks = json.loads(CHUNKS_FILE.read_text())
    print(f"Loaded {len(chunks)} chunks from {CHUNKS_FILE}")

    # ── embed ─────────────────────────────────────────────────────────────────
    print(f"Loading model: {MODEL_NAME}")
    model = SentenceTransformer(MODEL_NAME)

    texts = [c["text"] for c in chunks]
    print(f"Embedding {len(texts)} chunks …")
    embeddings = model.encode(texts, show_progress_bar=True, batch_size=32)
    print(f"Embedding shape: {embeddings.shape}")   # (N, 384)

    # ── build per-chunk metadata ──────────────────────────────────────────────
    # Track each chunk's position within its source document so we can
    # show "chunk 3 of 12 from NEU FAQs" during retrieval / attribution.
    source_counter: dict[str, int] = {}
    metadatas = []
    for c in chunks:
        src = c["source"]
        idx = source_counter.get(src, 0)
        source_counter[src] = idx + 1
        metadatas.append({
            "source":      src,
            "url":         c["url"],
            "chunk_index": idx,           # 0-based position within this source
            "token_est":   c.get("token_est", 0),
        })

    # ── upsert into ChromaDB ──────────────────────────────────────────────────
    client = chromadb.PersistentClient(path=CHROMA_PATH)

    # Always drop and recreate so re-runs start from a clean slate.
    # chunk IDs are new UUIDs each time chunk_documents.py runs, so upsert
    # would accumulate stale records instead of replacing them.
    try:
        client.delete_collection(COLLECTION)
        print(f"Dropped existing collection '{COLLECTION}'")
    except Exception:
        pass   # collection didn't exist yet

    collection = client.create_collection(
        name=COLLECTION,
        metadata={"hnsw:space": "cosine"},   # cosine similarity for sentence embeddings
    )

    collection.upsert(
        ids        = [c["id"] for c in chunks],
        embeddings = embeddings.tolist(),
        documents  = texts,
        metadatas  = metadatas,
    )

    stored = collection.count()
    print(f"\n✓ Upserted {len(chunks)} chunks → ChromaDB collection '{COLLECTION}'")
    print(f"  Total records in collection: {stored}")
    print(f"  Database path: {Path(CHROMA_PATH).resolve()}")


if __name__ == "__main__":
    run()
