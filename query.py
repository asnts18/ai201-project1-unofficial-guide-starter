"""
query.py — Generation layer (Milestone 5)
-----------------------------------------
Connects retrieval → Groq LLM → formatted answer.

Public API
----------
ask(question, top_k=5) -> dict
    {
        "answer":   str,          # LLM response, grounded in retrieved context
        "sources":  list[str],    # deduplicated source names
        "chunks":   list[dict],   # raw retrieval hits (text, source, url, score)
    }

Prompt design (from planning.md §AI Tool Plan)
----------------------------------------------
- Answer ONLY from retrieved context; never invent or infer beyond it.
- If the context doesn't cover the question, say so explicitly.
- Cite every source used, by name, inside the answer.
- Keep answers concise — one paragraph or a short list.
- Flag uncertainty when sources conflict (e.g. informal advice vs. official policy).
"""

import os
from dotenv import load_dotenv
from groq import Groq
from retrieval import retrieve

load_dotenv()

# ── Groq config ────────────────────────────────────────────────────────────────
GROQ_MODEL   = "llama-3.3-70b-versatile"   # fast, free-tier Groq model
MAX_TOKENS   = 512
TEMPERATURE  = 0.2    # low temperature → factual, deterministic answers

# ── prompt template ────────────────────────────────────────────────────────────
SYSTEM_PROMPT = """\
You are a housing advisor for Northeastern University students looking for off-campus housing in Boston.

Answer questions using ONLY the information provided in the context documents below.
Rules:
1. If the context does not contain enough information to answer the question, respond with exactly:
   "I don't have enough information on that based on my sources."
   Do NOT guess, infer, or use general knowledge.
2. Keep answers concise — one short paragraph or a brief bulleted list.
3. At the end of every answer, add a "Sources:" line listing the document name(s)
   you drew from, e.g.: Sources: NEU Off-Campus Housing FAQs, Massachusetts Landlord-Tenant Law
4. If sources give conflicting advice (e.g. a student opinion vs. an official policy),
   note the conflict briefly rather than picking one side.
"""

def _build_user_message(question: str, chunks: list[dict]) -> str:
    """Format retrieved chunks as numbered context blocks, then append the question."""
    context_blocks = []
    for i, chunk in enumerate(chunks, 1):
        context_blocks.append(
            f"[{i}] {chunk['source']}\n{chunk['text']}"
        )
    context = "\n\n".join(context_blocks)
    return (
        f"Context documents:\n\n{context}\n\n"
        f"---\n"
        f"Question: {question}\n\n"
        f"Answer only from the context above. Cite sources at the end."
    )


# ── main entry point ───────────────────────────────────────────────────────────

def ask(question: str, top_k: int = 5) -> dict:
    """
    Full RAG pipeline: retrieve → generate → return structured result.

    Parameters
    ----------
    question : str   — user's natural-language question
    top_k    : int   — number of chunks to retrieve (default 5)

    Returns
    -------
    dict with keys:
        answer  — LLM-generated answer string
        sources — deduplicated list of source document names
        chunks  — raw retrieval results for debugging / display
    """
    # ── Step 1: retrieve relevant chunks ──────────────────────────────────────
    chunks = retrieve(question, top_k=top_k)

    # If every retrieved chunk is a very weak match, tell the user upfront
    # rather than sending low-quality context to the LLM.
    WEAK_DISTANCE_THRESHOLD = 0.70
    if chunks and chunks[0]["distance"] > WEAK_DISTANCE_THRESHOLD:
        return {
            "answer": "I don't have enough information on that based on my sources.",
            "sources": [],
            "chunks": chunks,
        }

    # ── Step 2: build prompt ───────────────────────────────────────────────────
    user_message = _build_user_message(question, chunks)

    # ── Step 3: call Groq ──────────────────────────────────────────────────────
    client = Groq(api_key=os.environ["GROQ_API_KEY"])
    response = client.chat.completions.create(
        model=GROQ_MODEL,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user",   "content": user_message},
        ],
        max_tokens=MAX_TOKENS,
        temperature=TEMPERATURE,
    )
    answer = response.choices[0].message.content.strip()

    # ── Step 4: programmatic source attribution ───────────────────────────────
    # Collect unique source names from retrieved chunks (ordered by relevance)
    # so attribution is guaranteed even if the model omits the Sources: line.
    seen: set[str] = set()
    sources: list[str] = []
    for chunk in chunks:
        s = chunk["source"]
        if s not in seen:
            seen.add(s)
            sources.append(s)

    return {
        "answer":  answer,
        "sources": sources,
        "chunks":  chunks,
    }


# ── CLI smoke-test ─────────────────────────────────────────────────────────────
if __name__ == "__main__":
    test_questions = [
        "How much do I need to pay upfront when renting in Boston?",
        "What changed about broker fees in Boston in 2025?",
        "How do I verify a listing isn't a scam?",
        "What neighborhoods near Northeastern have T access?",
    ]

    for q in test_questions:
        print(f"\n{'═' * 65}")
        print(f"Q: {q}")
        print("═" * 65)
        result = ask(q)
        print(result["answer"])
        print(f"\n[Retrieved from: {', '.join(result['sources'])}]")
        print(f"[Top chunk distance: {result['chunks'][0]['distance']:.4f}]")
