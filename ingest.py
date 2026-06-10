"""
Ingestion and chunking pipeline — Milestone 3
----------------------------------------------
Sources (from planning.md Documents table):
  - 8 HTML web pages  → requests + BeautifulSoup
  - 1 PDF             → pdfplumber
  - 1 Reddit thread   → Reddit JSON API (no credentials required)

Chunking (from planning.md Chunking Strategy):
  - Target chunk size : 300–600 tokens  (implemented as ~400-token midpoint)
  - Overlap           : 100–150 tokens  (implemented as 100-token lower bound)
  - Token estimate    : characters / 4  (standard English approximation)
  - Reddit is chunked comment-by-comment first, then split if a single
    comment exceeds the target size, preserving conversational context.

Output: chunks.json — list of {id, text, source, url}
"""

import json
import re
import time
import uuid
from io import BytesIO
from pathlib import Path

import requests
from bs4 import BeautifulSoup

try:
    import pdfplumber
    HAS_PDFPLUMBER = True
except ImportError:
    HAS_PDFPLUMBER = False
    print("WARNING: pdfplumber not installed — PDF source will be skipped.")

# ── chunking constants ─────────────────────────────────────────────────────────
CHARS_PER_TOKEN = 4        # rough approximation for English text
TARGET_CHARS    = 400 * CHARS_PER_TOKEN   # 1 600 chars  (~400 tokens)
OVERLAP_CHARS   = 100 * CHARS_PER_TOKEN   #   400 chars  (~100 tokens)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0 Safari/537.36"
    )
}

# ── source registry (planning.md §Documents) ──────────────────────────────────
SOURCES = [
    {
        "source": "NEU Off-Campus Neighborhoods",
        "url": "https://offcampus.housing.northeastern.edu/get-started/neighborhoods/",
        "type": "html",
    },
    {
        "source": "NEU Off-Campus Housing FAQs",
        "url": "https://offcampus.housing.northeastern.edu/advising-and-support-resources/discussfrequently-asked-questions/",
        "type": "html",
    },
    {
        "source": "Renting in Boston (boston.gov)",
        "url": "https://www.boston.gov/renting-boston",
        "type": "html",
    },
    {
        "source": "Top Neighborhoods for NEU Students",
        "url": "https://offcampusapartmentfinder.com/top-neighborhoods-for-northeastern-students-living-off%E2%80%91campus/",
        "type": "html",
    },
    {
        "source": "NEU OGS International Student Guide",
        "url": "https://bpb-us-e1.wpmucdn.com/sites.northeastern.edu/dist/1/555/files/2023/06/InternationalStudentBrochure2023-FINAL.pdf",
        "type": "pdf",
    },
    {
        "source": "SpotEasy Off-Campus Housing Guide",
        "url": "https://www.spoteasy.com/blog/how-does-off-campus-housing-near-northeastern-actually-work",
        "type": "html",
    },
    {
        "source": "NEU Rental Scams Guide",
        "url": "https://offcampus.housing.northeastern.edu/explore-housing-options/rental-scams/",
        "type": "html",
    },
    {
        "source": "Massachusetts Landlord-Tenant Law",
        "url": "https://www.mass.gov/info-details/massachusetts-law-about-landlord-and-tenant",
        "type": "html",
        # mass.gov blocks automated requests; save the page as documents/mass_landlord.html
        "local_file": "documents/mass_landlord.html",
    },
    {
        "source": "Boston Broker Fee Guidance",
        "url": "https://www.boston.gov/departments/housing/office-housing-stability/broker-fees-3-things-know-about-new-law",
        "type": "html",
    },
    {
        "source": "NEU Housing Megathread (Reddit r/NEU)",
        "url": "https://www.reddit.com/r/NEU/comments/11eo62e/megathread_please_post_all_housing_and_roommate/",
        "type": "reddit",
        # Reddit now blocks unauthenticated JSON requests; save the thread as
        # documents/reddit_megathread.html (browser Save As) as a fallback.
        "local_file": "documents/reddit_megathread.html",
    },
]


# ── text cleaning ──────────────────────────────────────────────────────────────

def clean(text: str) -> str:
    """Normalise whitespace and strip common web boilerplate patterns."""
    text = re.sub(r"\s+", " ", text)               # collapse runs of whitespace
    text = re.sub(r" {2,}", " ", text)              # double-spaces → single
    text = re.sub(r"(\n){3,}", "\n\n", text)        # triple+ newlines → double
    text = text.strip()
    return text


# ── splitting helpers ──────────────────────────────────────────────────────────

def split_into_sentences(text: str) -> list[str]:
    """Split text on sentence boundaries, keeping the delimiter attached."""
    parts = re.split(r"(?<=[.!?])\s+", text)
    return [p.strip() for p in parts if p.strip()]


def chunk_text(text: str, source: str, url: str) -> list[dict]:
    """
    Split `text` into overlapping chunks targeting ~400 tokens (1 600 chars).
    Overlap is ~100 tokens (400 chars).  Splits at sentence boundaries where
    possible so chunks stay semantically coherent.
    """
    sentences = split_into_sentences(text)
    chunks = []
    current = []
    current_len = 0

    for sentence in sentences:
        slen = len(sentence)
        if current_len + slen > TARGET_CHARS and current:
            # emit current chunk
            chunk_text_str = " ".join(current)
            chunks.append(_make_chunk(chunk_text_str, source, url))

            # roll back by OVERLAP_CHARS worth of sentences for the next chunk
            overlap_buf, overlap_len = [], 0
            for s in reversed(current):
                if overlap_len + len(s) > OVERLAP_CHARS:
                    break
                overlap_buf.insert(0, s)
                overlap_len += len(s)

            current = overlap_buf
            current_len = overlap_len

        current.append(sentence)
        current_len += slen

    if current:
        chunks.append(_make_chunk(" ".join(current), source, url))

    return chunks


def _make_chunk(text: str, source: str, url: str) -> dict:
    return {"id": str(uuid.uuid4()), "text": text, "source": source, "url": url}


# ── fetchers ───────────────────────────────────────────────────────────────────

def fetch_html(url: str, source: str, local_file: str | None = None) -> list[dict]:
    """Download an HTML page and extract its main body text.
    Falls back to local_file if the remote request fails (e.g. 403)."""
    html = None
    if local_file and Path(local_file).exists():
        html = Path(local_file).read_text(encoding="utf-8", errors="replace")
        print(f"  [LOCAL] {source}: reading {local_file}")
    else:
        try:
            resp = requests.get(url, headers=HEADERS, timeout=15)
            resp.raise_for_status()
            html = resp.text
        except requests.RequestException as e:
            print(f"  [WARN] Could not fetch {url}: {e}")
            if local_file:
                print(f"         → Save the page to '{local_file}' to include it.")
            return []

    soup = BeautifulSoup(html, "html.parser")

    # remove navigation, header, footer, scripts, styles
    for tag in soup(["script", "style", "nav", "header", "footer",
                     "aside", "form", "noscript", "iframe"]):
        tag.decompose()

    # prefer <main> or <article>, fall back to <body>
    main = soup.find("main") or soup.find("article") or soup.find("body")
    if main is None:
        return []

    text = clean(main.get_text(separator=" "))
    if len(text) < 200:
        print(f"  [WARN] Very short text for {source} ({len(text)} chars)")
        return []

    print(f"  [OK] {source}: {len(text):,} chars")
    return chunk_text(text, source, url)


def fetch_pdf(url: str, source: str) -> list[dict]:
    """Download a PDF and extract all page text."""
    if not HAS_PDFPLUMBER:
        return []

    try:
        resp = requests.get(url, headers=HEADERS, timeout=30)
        resp.raise_for_status()
    except requests.RequestException as e:
        print(f"  [WARN] Could not fetch PDF {url}: {e}")
        return []

    pages_text = []
    with pdfplumber.open(BytesIO(resp.content)) as pdf:
        for page in pdf.pages:
            page_text = page.extract_text()
            if page_text:
                pages_text.append(clean(page_text))

    full_text = " ".join(pages_text)
    if not full_text.strip():
        print(f"  [WARN] No text extracted from PDF: {source}")
        return []

    print(f"  [OK] {source}: {len(full_text):,} chars across {len(pages_text)} pages")
    return chunk_text(full_text, source, url)


def _flatten_reddit_comments(comments: list, depth: int = 0) -> list[str]:
    """
    Recursively flatten a Reddit comment tree into a list of strings.
    Depth-1 comments get their parent prefix so replies stay in context.
    """
    texts = []
    for item in comments:
        if not isinstance(item, dict):
            continue
        data = item.get("data", {})
        body = data.get("body", "")
        if body and body not in ("[deleted]", "[removed]", ""):
            prefix = "  > " if depth > 0 else ""
            texts.append(clean(prefix + body))

        # recurse into replies
        replies = data.get("replies", "")
        if isinstance(replies, dict):
            children = replies.get("data", {}).get("children", [])
            texts.extend(_flatten_reddit_comments(children, depth + 1))

    return texts


def _parse_reddit_html(html: str, source: str, url: str) -> list[dict]:
    """Extract comment text from a browser-saved Reddit HTML page."""
    soup = BeautifulSoup(html, "html.parser")
    # Reddit's new layout stores comment bodies in <div data-testid="comment">
    # or in <p> tags inside .Comment class elements; grab all visible paragraphs
    # inside comment containers as a best-effort extraction.
    comment_els = (
        soup.select("[data-testid='comment'] p") or
        soup.select(".Comment p") or
        soup.find_all("p")   # last-resort fallback
    )
    texts = [clean(el.get_text()) for el in comment_els if el.get_text(strip=True)]
    if not texts:
        print(f"  [WARN] Could not extract comments from local HTML for {source}")
        return []

    print(f"  [LOCAL] {source}: {len(texts)} comment paragraphs")
    chunks = []
    buffer, buffer_len = [], 0
    for t in texts:
        if buffer_len + len(t) > TARGET_CHARS and buffer:
            chunks.extend(chunk_text(" ".join(buffer), source, url))
            buffer, buffer_len = [], 0
        buffer.append(t)
        buffer_len += len(t)
    if buffer:
        chunks.extend(chunk_text(" ".join(buffer), source, url))
    return chunks


def fetch_reddit(url: str, source: str, local_file: str | None = None) -> list[dict]:
    """
    Fetch a Reddit thread via the Reddit JSON API (no credentials needed).
    Falls back to parsing a locally saved HTML file if the API is blocked.
    Each comment becomes its own unit; short comments are batched together
    before chunking to avoid micro-chunks from brief replies.
    """
    # ── try local HTML fallback first if file exists ──────────────────────────
    if local_file and Path(local_file).exists():
        print(f"  [LOCAL] {source}: reading {local_file}")
        return _parse_reddit_html(Path(local_file).read_text("utf-8", errors="replace"),
                                  source, url)

    # ── try Reddit JSON API ───────────────────────────────────────────────────
    json_url = url.rstrip("/") + ".json?limit=500"
    reddit_headers = {**HEADERS, "Accept": "application/json"}

    try:
        resp = requests.get(json_url, headers=reddit_headers, timeout=15)
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        print(f"  [WARN] Could not fetch Reddit thread {url}: {e}")
        if local_file:
            print(f"         → Save the thread page to '{local_file}' to include it.")
        return []

    # data[0] is the post listing; data[1] is the comments listing
    post_data = data[0]["data"]["children"][0]["data"]
    post_title = clean(post_data.get("title", ""))
    post_body  = clean(post_data.get("selftext", ""))

    comment_children = data[1]["data"]["children"]
    comment_texts = _flatten_reddit_comments(comment_children)

    print(f"  [OK] {source}: {len(comment_texts)} comments")

    chunks = []

    # chunk the post itself (title + body) as a single unit
    post_full = f"{post_title}\n\n{post_body}".strip()
    if post_full:
        chunks.extend(chunk_text(post_full, source, url))

    # group comments into windows; short comments are batched up to TARGET_CHARS
    # before being emitted so we don't get one-sentence chunks from brief replies
    buffer, buffer_len = [], 0
    for comment in comment_texts:
        clen = len(comment)
        if buffer_len + clen > TARGET_CHARS and buffer:
            combined = " ".join(buffer)
            chunks.extend(chunk_text(combined, source, url))
            buffer, buffer_len = [], 0
        buffer.append(comment)
        buffer_len += clen

    if buffer:
        combined = " ".join(buffer)
        chunks.extend(chunk_text(combined, source, url))

    return chunks


# ── main pipeline ──────────────────────────────────────────────────────────────

FETCHERS = {
    "html":   fetch_html,
    "pdf":    fetch_pdf,
    "reddit": fetch_reddit,
}


def run_pipeline() -> None:
    all_chunks: list[dict] = []

    for doc in SOURCES:
        print(f"\nIngesting: {doc['source']}")
        fetcher = FETCHERS[doc["type"]]
        local = doc.get("local_file")
        chunks = fetcher(doc["url"], doc["source"], local) if local else fetcher(doc["url"], doc["source"])
        all_chunks.extend(chunks)
        time.sleep(0.5)   # polite crawl delay

    out_path = Path("chunks.json")
    out_path.write_text(json.dumps(all_chunks, indent=2, ensure_ascii=False))

    total_chars = sum(len(c["text"]) for c in all_chunks)
    avg_chars   = total_chars // len(all_chunks) if all_chunks else 0
    avg_tokens  = avg_chars // CHARS_PER_TOKEN

    print(f"\n{'─'*50}")
    print(f"Total chunks  : {len(all_chunks)}")
    print(f"Avg chunk size: {avg_chars} chars (~{avg_tokens} tokens)")
    print(f"Output saved  : {out_path.resolve()}")
    print(f"{'─'*50}")


if __name__ == "__main__":
    run_pipeline()
