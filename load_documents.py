"""
load_documents.py — Document loading and cleaning step
-------------------------------------------------------
Step 1 — Fetch every source and write raw content to documents/raw/
Step 2 — Clean each raw file and write to documents/cleaned/
Step 3 — Print one cleaned document so you can inspect the output

Raw format:  documents/raw/<slug>.html  (HTML pages and Reddit HTML fallback)
             documents/raw/<slug>.txt   (Reddit JSON flattened to plain text)
             documents/raw/<slug>.pdf   (binary PDF download)

Cleaned format: documents/cleaned/<slug>.txt  (plain UTF-8 text, ready to chunk)
"""

import html as html_lib
import json
import re
import sys
import time
from io import BytesIO
from pathlib import Path

import requests
from bs4 import BeautifulSoup, Comment

try:
    import pdfplumber
    HAS_PDFPLUMBER = True
except ImportError:
    HAS_PDFPLUMBER = False

# ── directories ────────────────────────────────────────────────────────────────
RAW_DIR     = Path("documents/raw")
CLEANED_DIR = Path("documents/cleaned")
RAW_DIR.mkdir(parents=True, exist_ok=True)
CLEANED_DIR.mkdir(parents=True, exist_ok=True)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0 Safari/537.36"
    )
}

# ── source registry ────────────────────────────────────────────────────────────
SOURCES = [
    {
        "slug":   "neu_neighborhoods",
        "source": "NEU Off-Campus Neighborhoods",
        "url":    "https://offcampus.housing.northeastern.edu/get-started/neighborhoods/",
        "type":   "html",
    },
    {
        "slug":   "neu_faqs",
        "source": "NEU Off-Campus Housing FAQs",
        "url":    "https://offcampus.housing.northeastern.edu/advising-and-support-resources/discussfrequently-asked-questions/",
        "type":   "html",
    },
    {
        "slug":       "boston_renting",
        "source":     "Renting in Boston (boston.gov)",
        "url":        "https://www.boston.gov/renting-boston",
        "type":       "html",
        # boston.gov uses Incapsula bot protection; save the page manually
        "local_file": "documents/boston_renting.html",
    },
    {
        "slug":   "neu_top_neighborhoods",
        "source": "Top Neighborhoods for NEU Students",
        "url":    "https://offcampusapartmentfinder.com/top-neighborhoods-for-northeastern-students-living-off%E2%80%91campus/",
        "type":   "html",
    },
    {
        "slug":       "neu_ogs_guide",
        "source":     "NEU OGS International Student Guide",
        "url":        "https://bpb-us-e1.wpmucdn.com/sites.northeastern.edu/dist/1/555/files/2023/06/InternationalStudentBrochure2023-FINAL.pdf",
        "type":       "pdf",
    },
    {
        "slug":   "spoteasy_guide",
        "source": "SpotEasy Off-Campus Housing Guide",
        "url":    "https://www.spoteasy.com/blog/how-does-off-campus-housing-near-northeastern-actually-work",
        "type":   "html",
    },
    {
        "slug":   "neu_scams",
        "source": "NEU Rental Scams Guide",
        "url":    "https://offcampus.housing.northeastern.edu/explore-housing-options/rental-scams/",
        "type":   "html",
    },
    {
        "slug":       "mass_landlord_law",
        "source":     "Massachusetts Landlord-Tenant Law",
        "url":        "https://www.mass.gov/info-details/massachusetts-law-about-landlord-and-tenant",
        "type":       "html",
        "local_file": "documents/mass_landlord.html",
    },
    {
        "slug":       "boston_broker_fee",
        "source":     "Boston Broker Fee Guidance",
        "url":        "https://www.boston.gov/departments/housing/office-housing-stability/broker-fees-3-things-know-about-new-law",
        "type":       "html",
        # boston.gov uses Incapsula bot protection; save the page manually
        "local_file": "documents/boston_broker_fee.html",
    },
    {
        "slug":       "reddit_megathread",
        "source":     "NEU Housing Megathread (Reddit r/NEU)",
        "url":        "https://www.reddit.com/r/NEU/comments/11eo62e/megathread_please_post_all_housing_and_roommate/",
        "type":       "reddit",
        "local_file": "documents/reddit_megathread.html",
    },
]


# ══════════════════════════════════════════════════════════════════════════════
# STEP 1 — FETCH AND SAVE RAW
# ══════════════════════════════════════════════════════════════════════════════

def fetch_raw(doc: dict) -> bool:
    """Download a source and save it verbatim under documents/raw/. Returns True on success."""
    slug = doc["slug"]
    dtype = doc["type"]
    url   = doc["url"]

    # ── HTML ──────────────────────────────────────────────────────────────────
    if dtype == "html":
        local = doc.get("local_file")
        if local and Path(local).exists():
            raw_html = Path(local).read_text("utf-8", errors="replace")
            out = RAW_DIR / f"{slug}.html"
            out.write_text(raw_html, encoding="utf-8")
            print(f"  [LOCAL→RAW] {slug}.html  ({len(raw_html):,} bytes)")
            return True
        try:
            resp = requests.get(url, headers=HEADERS, timeout=15)
            resp.raise_for_status()
            if "_Incapsula_Resource" in resp.text or len(resp.text) < 500:
                print(f"  [BLOCKED] {slug}: bot protection detected")
                if local:
                    print(f"         → Save the page to '{local}' to include it.")
                return False
            out = RAW_DIR / f"{slug}.html"
            out.write_text(resp.text, encoding="utf-8")
            print(f"  [FETCH→RAW] {slug}.html  ({len(resp.text):,} bytes)")
            return True
        except requests.RequestException as e:
            print(f"  [SKIP] {slug}: {e}")
            if local:
                print(f"         → Save the page to '{local}' to include it.")
            return False

    # ── PDF ───────────────────────────────────────────────────────────────────
    if dtype == "pdf":
        try:
            resp = requests.get(url, headers=HEADERS, timeout=30)
            resp.raise_for_status()
            out = RAW_DIR / f"{slug}.pdf"
            out.write_bytes(resp.content)
            print(f"  [FETCH→RAW] {slug}.pdf  ({len(resp.content):,} bytes)")
            return True
        except requests.RequestException as e:
            print(f"  [SKIP] {slug}: {e}")
            return False

    # ── Reddit ────────────────────────────────────────────────────────────────
    if dtype == "reddit":
        local = doc.get("local_file")
        if local and Path(local).exists():
            raw_html = Path(local).read_text("utf-8", errors="replace")
            out = RAW_DIR / f"{slug}.html"
            out.write_text(raw_html, encoding="utf-8")
            print(f"  [LOCAL→RAW] {slug}.html  ({len(raw_html):,} bytes)")
            return True

        json_url = url.rstrip("/") + ".json?limit=500"
        try:
            resp = requests.get(json_url, headers={**HEADERS, "Accept": "application/json"}, timeout=15)
            resp.raise_for_status()
            data = resp.json()

            # Flatten to plain text so the raw file is human-readable
            lines = []
            post = data[0]["data"]["children"][0]["data"]
            lines.append("TITLE: " + post.get("title", ""))
            lines.append("BODY: " + post.get("selftext", ""))
            lines.append("")
            lines += _flatten_reddit_to_lines(data[1]["data"]["children"])
            raw_text = "\n".join(lines)

            out = RAW_DIR / f"{slug}.txt"
            out.write_text(raw_text, encoding="utf-8")
            print(f"  [FETCH→RAW] {slug}.txt  ({len(raw_text):,} chars)")
            return True
        except Exception as e:
            print(f"  [SKIP] {slug}: {e}")
            if local:
                print(f"         → Save the thread to '{local}' to include it.")
            return False

    return False


def _flatten_reddit_to_lines(comments: list, indent: int = 0) -> list[str]:
    lines = []
    for item in comments:
        if not isinstance(item, dict):
            continue
        data = item.get("data", {})
        body = data.get("body", "")
        if body and body not in ("[deleted]", "[removed]"):
            lines.append("  " * indent + body)
        replies = data.get("replies", "")
        if isinstance(replies, dict):
            lines += _flatten_reddit_to_lines(
                replies.get("data", {}).get("children", []), indent + 1
            )
    return lines


# ══════════════════════════════════════════════════════════════════════════════
# STEP 2 — CLEAN
# ══════════════════════════════════════════════════════════════════════════════

# CSS selectors whose content is always boilerplate (nav, ads, cookie banners…)
_BOILERPLATE_SELECTORS = [
    # structural chrome
    "nav", "header", "footer", "aside",
    # semantic roles
    '[role="navigation"]', '[role="banner"]', '[role="contentinfo"]',
    '[role="complementary"]', '[role="search"]',
    # ids / classes seen on target sites
    "#cookie", "#cookies", "#cookie-banner", "#cookie-notice",
    ".cookie", ".cookie-banner", ".cookie-notice", ".cookie-consent",
    ".nav", ".navbar", ".navigation", ".breadcrumb", ".breadcrumbs",
    ".site-header", ".site-footer", ".page-header",
    ".sidebar", ".widget", ".widget-area", ".related-posts",
    ".share", ".share-buttons", ".social-share", ".social-links",
    ".comment-count", ".comments-link", ".post-meta", ".entry-meta",
    ".read-more", ".more-link", ".btn-read-more",
    ".pagination", ".pager", ".wp-pagenavi",
    ".advertisement", ".ads", ".ad-slot", ".ad-container",
    ".popup", ".modal", ".overlay",
    '[aria-label="breadcrumb"]', '[aria-label="site navigation"]',
    # mass.gov specifics — pre-content is page metadata; post-content is related-links sidebar
    ".pre-content", ".post-content", ".ma__mass-feedback-form",
    # boston.gov specifics
    ".b--g", ".b-c", ".bra-contact-details",
    # NEU site chrome
    ".global-header", ".global-footer", ".utility-nav",
]

# Short lines that are pure navigation / button text (case-insensitive exact match)
_NAV_PHRASES = {
    "home", "search", "menu", "close", "open", "back", "next", "previous",
    "skip to content", "skip to main content", "skip navigation",
    "read more", "learn more", "click here", "find out more", "more info",
    "share", "tweet", "facebook", "instagram", "linkedin", "youtube",
    "print", "email", "subscribe", "sign up", "log in", "login", "logout",
    "contact us", "about us", "privacy policy", "terms of use",
    "cookie settings", "accept cookies", "accept all", "manage cookies",
    "newsletter", "follow us",
    "×", "✕", "›", "‹", "»", "«",
}


def _strip_boilerplate_tags(soup: BeautifulSoup) -> None:
    """Remove elements that are never substantive content."""
    # remove HTML comments
    for comment in soup.find_all(string=lambda t: isinstance(t, Comment)):
        comment.extract()

    # remove by tag names that never carry content
    for tag in soup(["script", "style", "noscript", "iframe",
                     "form", "button", "input", "select", "textarea",
                     "svg", "canvas", "figure > figcaption"]):
        tag.decompose()

    # remove by boilerplate selectors
    for sel in _BOILERPLATE_SELECTORS:
        for el in soup.select(sel):
            el.decompose()

    # remove elements whose text is only a single short nav phrase
    for el in soup.find_all(True):
        txt = el.get_text(strip=True).lower()
        if txt in _NAV_PHRASES:
            el.decompose()


def _decode_entities(text: str) -> str:
    """Resolve HTML entities left over after get_text()."""
    # html.unescape handles &amp; &nbsp; &lt; &gt; &#160; etc.
    text = html_lib.unescape(text)
    # non-breaking space → regular space
    text = text.replace(" ", " ")
    return text


def _remove_url_lines(text: str) -> str:
    """Drop lines that are just a bare URL with no surrounding text."""
    lines = text.splitlines()
    cleaned = []
    for line in lines:
        stripped = line.strip()
        if re.match(r"^https?://\S+$", stripped):
            continue
        cleaned.append(line)
    return "\n".join(cleaned)


def _remove_short_orphan_lines(text: str, min_words: int = 4) -> str:
    """
    Remove lines that are too short to be substantive and look like
    nav labels, menu items, or share-button text.
    Lines inside a run of normal prose (>=min_words words) are kept.
    """
    lines = text.splitlines()
    result = []
    for line in lines:
        stripped = line.strip()
        # keep blank lines (paragraph separators)
        if not stripped:
            result.append("")
            continue
        words = stripped.split()
        if len(words) < min_words and stripped.lower() in _NAV_PHRASES:
            continue
        # drop very short all-caps lines (common for nav labels: "HOUSING", "HOME")
        if len(words) <= 2 and stripped.isupper():
            continue
        result.append(line)
    return "\n".join(result)


def _rejoin_inline_breaks(text: str) -> str:
    """
    Re-join lines that are mid-sentence fragments left by inline HTML whitespace.
    A line is treated as a fragment (and merged into the previous line) when:
      - The previous line does not end a sentence (.!?:;) and is not a heading, AND
      - This line does not look like a new sentence (doesn't start with a capital
        that follows a sentence-ending predecessor) or is very short (<= 60 chars).
    Blank lines are always preserved as paragraph separators.
    """
    lines = text.splitlines()
    result: list[str] = []
    SENTENCE_END = re.compile(r"[.!?:;]\s*$")

    for line in lines:
        stripped = line.strip()
        if not stripped:
            result.append("")
            continue

        # Drop lines that are only punctuation with no word content (empty link remnants)
        if re.match(r"^[.!?,;:\s]+$", stripped):
            # Attach trailing punctuation to the previous line instead of orphaning it
            if result and result[-1].strip():
                result[-1] = result[-1].rstrip() + stripped.lstrip()
            continue

        if result and result[-1].strip():
            prev = result[-1].strip()
            # merge when: prev doesn't end a sentence AND this line starts with
            # lowercase, leading punctuation (broken inline), or is very short
            is_continuation = (
                not SENTENCE_END.search(prev) and
                (
                    stripped[0].islower() or
                    stripped[0] in ".,:;" or   # punctuation separated from anchor
                    len(stripped) <= 40
                )
            )
            if is_continuation:
                sep = "" if stripped[0] in ".,:;" else " "
                result[-1] = result[-1].rstrip() + sep + stripped
                continue

        result.append(line)

    return "\n".join(result)


def _remove_contact_blocks(text: str) -> str:
    """
    Strip repeated office/contact blocks that slip past tag-level cleaning.
    Matches patterns like phone numbers (617-xxx-xxxx), street addresses, and
    office-hours lines, then removes the whole run of lines around them.
    """
    lines = text.splitlines()
    result = []
    i = 0
    CONTACT_PAT = re.compile(
        r"(\b\d{3}[-.\s]\d{3}[-.\s]\d{4}\b"                                   # phone 617-635-4200
        r"|\b\d+\s+\w[\w\s]+(?:Street|St|Ave|Road|Rd|Court|Ct|Plaza|Blvd)\b"  # street address
        r"|\b[A-Z][a-z]+,\s+[A-Z]{2}\s+\d{5}\b"                               # City, ST 02108
        r"|Monday through|Hours:|a\.m\.|p\.m\."                                # office hours
        r"|Page Sections"                                                        # boston.gov nav label
        r"|Mayor's Office|Office of Housing|Housing Stability"                  # boston.gov dept names
        r")", re.I
    )
    while i < len(lines):
        if CONTACT_PAT.search(lines[i]):
            # skip this line and any immediately following contact-looking lines
            i += 1
            while i < len(lines) and (not lines[i].strip() or CONTACT_PAT.search(lines[i])):
                i += 1
        else:
            result.append(lines[i])
            i += 1
    return "\n".join(result)


def _normalise_whitespace(text: str) -> str:
    lines = [l.rstrip() for l in text.splitlines()]
    # collapse 3+ consecutive blank lines to a single blank
    result, blanks = [], 0
    for line in lines:
        if line == "":
            blanks += 1
            if blanks <= 1:
                result.append("")
        else:
            blanks = 0
            result.append(line)
    return "\n".join(result).strip()


_INCAPSULA_MARKER = "_Incapsula_Resource"

# Inline tags whose text should flow with surrounding prose, not break to new lines
_INLINE_TAGS = {"a", "abbr", "acronym", "b", "bdo", "big", "br", "cite", "code",
                "dfn", "em", "i", "img", "input", "kbd", "label", "map", "object",
                "output", "q", "samp", "select", "small", "span", "strong", "sub",
                "sup", "textarea", "time", "tt", "u", "var"}


def clean_html(raw_html: str) -> str:
    # Detect bot-blocker pages (Incapsula, Cloudflare JS challenge, etc.)
    if _INCAPSULA_MARKER in raw_html or len(raw_html) < 500:
        return ""

    soup = BeautifulSoup(raw_html, "html.parser")
    _strip_boilerplate_tags(soup)

    # Unwrap inline tags so their text flows into the surrounding sentence
    # instead of being separated by newlines when get_text() runs.
    for tag in soup.find_all(_INLINE_TAGS):
        tag.unwrap()

    # prefer the most specific content container available
    content = (
        soup.find("main") or
        soup.find("article") or
        soup.find(id=re.compile(r"content|main|primary", re.I)) or
        soup.find(class_=re.compile(r"content|entry|post-body|article", re.I)) or
        soup.find("body")
    )
    if content is None:
        return ""

    text = content.get_text(separator="\n")
    text = _decode_entities(text)
    text = _rejoin_inline_breaks(text)
    text = _remove_contact_blocks(text)
    text = _remove_url_lines(text)
    text = _remove_short_orphan_lines(text)
    text = _normalise_whitespace(text)
    return text


def _find_column_gap(words: list, page_width: float) -> float | None:
    """
    Detect the x-coordinate of the whitespace gap between two columns.
    Builds a histogram of word x0 starts in 20px buckets; a gap is a
    bucket range with zero words that lies between 25% and 75% of the
    page width (so we don't mistake narrow margins for column gaps).
    Returns the midpoint of the gap, or None if no two-column layout.
    """
    if not words:
        return None
    lo, hi = page_width * 0.25, page_width * 0.75
    bucket_size = 20
    occupied: set[int] = set()
    for w in words:
        b = int(w["x0"] // bucket_size)
        occupied.add(b)

    # Find empty buckets within the middle half of the page
    gap_buckets = []
    for b in range(int(lo // bucket_size), int(hi // bucket_size) + 1):
        if b not in occupied:
            gap_buckets.append(b)

    if not gap_buckets:
        return None
    # Use the centre of the first contiguous run of empty buckets
    gap_mid = (gap_buckets[0] + 0.5) * bucket_size
    return gap_mid


def _words_to_text(words: list) -> str:
    """Reconstruct paragraph text from a list of word dicts, sorted by position."""
    if not words:
        return ""
    # Sort top-to-bottom, then left-to-right within each line
    words = sorted(words, key=lambda w: (round(w["top"], 0), w["x0"]))
    lines: list[list[str]] = []
    current_line: list[str] = [words[0]["text"]]
    current_top = words[0]["top"]
    for w in words[1:]:
        if abs(w["top"] - current_top) < 4:   # same line (4pt tolerance)
            current_line.append(w["text"])
        else:
            lines.append(current_line)
            current_line = [w["text"]]
            current_top  = w["top"]
    lines.append(current_line)
    return "\n".join(" ".join(line) for line in lines)


def _extract_pdf_page(page) -> str:
    """
    Extract text from one PDF page, handling two-column layouts.

    pdfplumber's default extract_text() reads words left-to-right across
    the full page width, which interleaves columns in a two-column brochure.
    We detect the column gap from the x0 histogram of all words, then
    reconstruct each column's text independently and concatenate them.
    """
    words = page.extract_words()
    if not words:
        return ""

    gap_x = _find_column_gap(words, page.width)

    if gap_x is not None:
        left_words  = [w for w in words if w["x1"] <= gap_x]
        right_words = [w for w in words if w["x0"] >= gap_x]
        if len(left_words) > 5 and len(right_words) > 5:
            return (_words_to_text(left_words) + "\n\n" + _words_to_text(right_words)).strip()

    # Single-column page (or gap detection failed) — fall back to default
    return page.extract_text() or ""


def clean_pdf(raw_path: Path) -> str:
    if not HAS_PDFPLUMBER:
        return ""
    pages = []
    with pdfplumber.open(raw_path) as pdf:
        for page in pdf.pages:
            t = _extract_pdf_page(page)
            if t:
                pages.append(t)
    text = "\n\n".join(pages)
    text = _decode_entities(text)
    text = _remove_contact_blocks(text)
    text = _remove_url_lines(text)
    text = _normalise_whitespace(text)
    return text


def clean_reddit_txt(raw_path: Path) -> str:
    """Clean already-flattened Reddit plain text (from JSON API path)."""
    text = raw_path.read_text("utf-8")
    text = _decode_entities(text)
    # drop "[deleted]" and "[removed]" lines
    lines = [l for l in text.splitlines()
             if l.strip() not in ("[deleted]", "[removed]", "")]
    text = "\n".join(lines)
    text = _normalise_whitespace(text)
    return text


def clean_reddit_html(raw_path: Path) -> str:
    """Clean a browser-saved Reddit HTML page."""
    raw_html = raw_path.read_text("utf-8", errors="replace")
    soup = BeautifulSoup(raw_html, "html.parser")

    # Reddit's shredded layout — pull comment bodies specifically
    comment_els = (
        soup.select("[data-testid='comment'] p") or
        soup.select(".Comment p") or
        soup.select("div[id^='t1_'] p")
    )
    if comment_els:
        texts = [el.get_text(separator=" ").strip() for el in comment_els if el.get_text(strip=True)]
    else:
        # fallback: full page clean
        _strip_boilerplate_tags(soup)
        body = soup.find("body") or soup
        texts = [body.get_text(separator="\n")]

    text = "\n\n".join(texts)
    text = _decode_entities(text)
    text = _remove_url_lines(text)
    text = _remove_short_orphan_lines(text)
    text = _normalise_whitespace(text)
    return text


def clean_document(doc: dict) -> str | None:
    """Read the raw file for `doc` and return cleaned plain text, or None if unavailable."""
    slug  = doc["slug"]
    dtype = doc["type"]

    if dtype in ("html", "reddit"):
        html_path = RAW_DIR / f"{slug}.html"
        txt_path  = RAW_DIR / f"{slug}.txt"

        if html_path.exists():
            if dtype == "reddit":
                return clean_reddit_html(html_path)
            return clean_html(html_path.read_text("utf-8", errors="replace"))

        if txt_path.exists() and dtype == "reddit":
            return clean_reddit_txt(txt_path)

    if dtype == "pdf":
        pdf_path = RAW_DIR / f"{slug}.pdf"
        if pdf_path.exists():
            return clean_pdf(pdf_path)

    return None


# ══════════════════════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════════════════════

def run() -> None:
    # ── Step 1: fetch and save raw ────────────────────────────────────────────
    print("=" * 60)
    print("STEP 1 — Fetching and saving raw documents")
    print("=" * 60)
    for doc in SOURCES:
        print(f"\n{doc['source']}")
        fetch_raw(doc)
        time.sleep(0.5)

    # ── Step 2: clean and save ────────────────────────────────────────────────
    print("\n" + "=" * 60)
    print("STEP 2 — Cleaning documents")
    print("=" * 60)
    cleaned_docs = {}
    for doc in SOURCES:
        slug = doc["slug"]
        text = clean_document(doc)
        if text and len(text) > 100:
            out = CLEANED_DIR / f"{slug}.txt"
            out.write_text(text, encoding="utf-8")
            cleaned_docs[slug] = text
            print(f"  [OK]   {slug}.txt  ({len(text):,} chars)")
        else:
            reason = "no raw file" if text is None else "too short after cleaning"
            print(f"  [SKIP] {slug}  ({reason})")

    # ── Step 3: print one document for inspection ─────────────────────────────
    print("\n" + "=" * 60)
    print("STEP 3 — Inspect: NEU Off-Campus Housing FAQs (neu_faqs)")
    print("=" * 60)
    inspect_slug = "neu_faqs"
    if inspect_slug in cleaned_docs:
        text = cleaned_docs[inspect_slug]
        print(f"\n[First 3 000 chars of {inspect_slug}.txt]\n")
        print(text[:3000])
        print("\n...\n")
        print(f"[Last 1 000 chars of {inspect_slug}.txt]\n")
        print(text[-1000:])
    else:
        # fallback to whatever was cleaned
        fallback = next(iter(cleaned_docs), None)
        if fallback:
            print(f"\n(neu_faqs not available, showing '{fallback}' instead)\n")
            print(cleaned_docs[fallback][:3000])

    print("\n" + "=" * 60)
    print(f"Done. {len(cleaned_docs)}/{len(SOURCES)} documents cleaned.")
    print(f"Raw files   → {RAW_DIR.resolve()}/")
    print(f"Cleaned files → {CLEANED_DIR.resolve()}/")
    print("=" * 60)


if __name__ == "__main__":
    run()
