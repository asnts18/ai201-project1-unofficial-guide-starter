"""
chunk_documents.py — Chunking step (Milestone 3)
-------------------------------------------------
Reads every .txt file from documents/cleaned/, applies the chunking
strategy from planning.md, and writes chunks.json.

planning.md spec:
  Chunk size : 300–600 tokens  → target 450 tokens (midpoint)
  Overlap    : 100–150 tokens  → target 125 tokens (midpoint)
  Token est. : characters / 4  (standard English approximation)

Chunking is sentence-aware: we never cut in the middle of a sentence.
We split on sentence boundaries and accumulate sentences until the
window reaches TARGET_CHARS, then step forward by (TARGET - OVERLAP)
chars so the next chunk re-uses the tail of the previous one.
"""

import json
import re
import uuid
from pathlib import Path

# ── tuneable constants (reflect planning.md spec) ─────────────────────────────
CHARS_PER_TOKEN = 4
TARGET_TOKENS   = 350    # lower end of 300–600 range (see planning.md for rationale)
OVERLAP_TOKENS  = 100    # lower bound of 100–150 range

TARGET_CHARS  = TARGET_TOKENS  * CHARS_PER_TOKEN   # 1 400 chars
OVERLAP_CHARS = OVERLAP_TOKENS * CHARS_PER_TOKEN   #   400 chars

CLEANED_DIR = Path("documents/cleaned")
OUTPUT_FILE = Path("chunks.json")

# ── slug → (source label, original URL) ───────────────────────────────────────
SOURCE_META = {
    "neu_neighborhoods":    ("NEU Off-Campus Neighborhoods",
                             "https://offcampus.housing.northeastern.edu/get-started/neighborhoods/"),
    "neu_faqs":             ("NEU Off-Campus Housing FAQs",
                             "https://offcampus.housing.northeastern.edu/advising-and-support-resources/discussfrequently-asked-questions/"),
    "boston_renting":       ("Renting in Boston (boston.gov)",
                             "https://www.boston.gov/renting-boston"),
    "neu_top_neighborhoods":("Top Neighborhoods for NEU Students",
                             "https://offcampusapartmentfinder.com/top-neighborhoods-for-northeastern-students-living-off%E2%80%91campus/"),
    "neu_ogs_guide":        ("NEU OGS International Student Guide",
                             "https://bpb-us-e1.wpmucdn.com/sites.northeastern.edu/dist/1/555/files/2023/06/InternationalStudentBrochure2023-FINAL.pdf"),
    "spoteasy_guide":       ("SpotEasy Off-Campus Housing Guide",
                             "https://www.spoteasy.com/blog/how-does-off-campus-housing-near-northeastern-actually-work"),
    "neu_scams":            ("NEU Rental Scams Guide",
                             "https://offcampus.housing.northeastern.edu/explore-housing-options/rental-scams/"),
    "mass_landlord_law":    ("Massachusetts Landlord-Tenant Law",
                             "https://www.mass.gov/info-details/massachusetts-law-about-landlord-and-tenant"),
    "boston_broker_fee":    ("Boston Broker Fee Guidance",
                             "https://www.boston.gov/departments/housing/office-housing-stability/broker-fees-3-things-know-about-new-law"),
    "reddit_megathread":    ("NEU Housing Megathread (Reddit r/NEU)",
                             "https://www.reddit.com/r/NEU/comments/11eo62e/megathread_please_post_all_housing_and_roommate/"),
}


# ── sentence splitter ──────────────────────────────────────────────────────────

def split_sentences(text: str) -> list[str]:
    """
    Split text into sentences.  Keeps the terminating punctuation attached to
    the sentence that owns it.  Handles common abbreviations (Mr., Dr., vs.)
    so we don't split mid-abbreviation.
    """
    # Protect common abbreviations from being treated as sentence ends
    text = re.sub(r"\b(Mr|Mrs|Ms|Dr|Prof|Sr|Jr|vs|etc|approx|est|apt|St|Ave|Blvd)\.",
                  r"\1<DOT>", text)
    # Split on . ! ? followed by whitespace + capital letter or end-of-string
    parts = re.split(r"(?<=[.!?])\s+(?=[A-Z\"\'])", text)
    # Restore protected dots
    return [p.replace("<DOT>", ".").strip() for p in parts if p.strip()]


# ── core chunker ───────────────────────────────────────────────────────────────

def chunk_text(text: str, source: str, url: str) -> list[dict]:
    """
    Produce overlapping chunks from `text`.

    Algorithm:
      1. Split into sentences.
      2. Accumulate sentences into a window until TARGET_CHARS is reached.
      3. Emit the window as a chunk.
      4. Drop sentences from the front of the window until the remaining
         content is <= OVERLAP_CHARS (i.e., step forward by TARGET - OVERLAP).
      5. Continue from step 2.
    """
    sentences = split_sentences(text)
    if not sentences:
        return []

    chunks: list[dict] = []
    window: list[str] = []
    window_len: int = 0

    for sentence in sentences:
        slen = len(sentence)

        # If adding this sentence would overflow and we already have content,
        # emit the current window as a chunk first.
        if window_len + slen > TARGET_CHARS and window:
            chunks.append(_make_chunk(window, source, url))

            # Step forward: drop sentences from the front until what remains
            # fits within OVERLAP_CHARS — this becomes the overlap for the
            # next chunk.
            while window and window_len > OVERLAP_CHARS:
                removed = window.pop(0)
                window_len -= len(removed)

        window.append(sentence)
        window_len += slen

    # Emit whatever is left in the window as the final chunk
    if window:
        chunks.append(_make_chunk(window, source, url))

    return chunks


def _make_chunk(sentences: list[str], source: str, url: str) -> dict:
    text = " ".join(sentences)
    tok_est = len(text) // CHARS_PER_TOKEN
    return {
        "id":         str(uuid.uuid4()),
        "text":       text,
        "source":     source,
        "url":        url,
        "token_est":  tok_est,
    }


# ── main ───────────────────────────────────────────────────────────────────────

def run() -> None:
    txt_files = sorted(CLEANED_DIR.glob("*.txt"))
    if not txt_files:
        print(f"No .txt files found in {CLEANED_DIR}. Run load_documents.py first.")
        return

    all_chunks: list[dict] = []
    rows: list[tuple] = []   # for the summary table

    for path in txt_files:
        slug = path.stem
        source, url = SOURCE_META.get(slug, (slug, ""))
        text = path.read_text("utf-8").strip()

        if not text:
            rows.append((slug, 0, 0, 0))
            continue

        doc_chunks = chunk_text(text, source, url)
        all_chunks.extend(doc_chunks)

        sizes = [c["token_est"] for c in doc_chunks]
        avg   = sum(sizes) // len(sizes) if sizes else 0
        rows.append((slug, len(text), len(doc_chunks), avg))

    # ── write output ──────────────────────────────────────────────────────────
    OUTPUT_FILE.write_text(json.dumps(all_chunks, indent=2, ensure_ascii=False))

    # ── summary table ─────────────────────────────────────────────────────────
    col = 30
    print(f"\n{'Document':<{col}} {'chars':>7}  {'chunks':>6}  {'avg tok':>7}")
    print("─" * (col + 26))
    for slug, chars, n, avg in rows:
        flag = "  ← single chunk (very short)" if n == 1 and chars < 1000 else ""
        print(f"{slug:<{col}} {chars:>7,}  {n:>6}  {avg:>7}{flag}")

    total_chunks = len(all_chunks)
    total_chars  = sum(r[1] for r in rows)
    all_sizes    = [c["token_est"] for c in all_chunks]
    overall_avg  = sum(all_sizes) // len(all_sizes) if all_sizes else 0
    overall_min  = min(all_sizes) if all_sizes else 0
    overall_max  = max(all_sizes) if all_sizes else 0

    print("─" * (col + 26))
    print(f"\nTotal chunks  : {total_chunks}")
    print(f"Total chars   : {total_chars:,}")
    print(f"Chunk size    : target={TARGET_TOKENS} tok, overlap={OVERLAP_TOKENS} tok")
    print(f"Token range   : min={overall_min}  avg={overall_avg}  max={overall_max}")
    print(f"Output        : {OUTPUT_FILE.resolve()}")

    # ── threshold check ───────────────────────────────────────────────────────
    print()
    if total_chunks < 50:
        print(f"⚠  {total_chunks} chunks is below the 50-chunk minimum.")
        print(f"   Chunks may be too large — consider reducing TARGET_TOKENS ({TARGET_TOKENS})")
        print(f"   or adding more documents.")
    elif total_chunks > 2000:
        print(f"⚠  {total_chunks} chunks exceeds the 2 000-chunk ceiling.")
        print(f"   Chunks may be too small — consider increasing TARGET_TOKENS ({TARGET_TOKENS})")
    else:
        print(f"✓  {total_chunks} chunks is within the 50–2 000 target range.")


if __name__ == "__main__":
    run()
