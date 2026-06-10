# The Unofficial Guide — Project 1

---

## Domain

This system covers **off-campus housing for Northeastern University students in Boston**. The domain is valuable because students face an unusually high-stakes rental market: Boston leases often open in October for September move-in, broker fees can equal a full month's rent, and the rules differ meaningfully from most other U.S. cities. Relevant knowledge is scattered across Northeastern's own advising pages, Massachusetts state law, Boston city guidance, and informal student-to-student advice. Students who miss key details (co-signer requirements, the 2025 broker fee law change, scam red flags) can lose money or end up in a bad lease.

---

## Document Sources

| # | Source | Type | URL or file path |
|---|--------|------|-----------------|
| 1 | NEU Off-Campus Neighborhoods | HTML | https://offcampus.housing.northeastern.edu/get-started/neighborhoods/ |
| 2 | NEU Off-Campus Housing FAQs | HTML | https://offcampus.housing.northeastern.edu/advising-and-support-resources/discussfrequently-asked-questions/ |
| 3 | Renting in Boston (boston.gov) | HTML | https://www.boston.gov/renting-boston |
| 4 | Top Neighborhoods for NEU Students | HTML | https://offcampusapartmentfinder.com/top-neighborhoods-for-northeastern-students-living-off%E2%80%91campus/ |
| 5 | NEU OGS International Student Guide | PDF | https://bpb-us-e1.wpmucdn.com/sites.northeastern.edu/dist/1/555/files/2023/06/InternationalStudentBrochure2023-FINAL.pdf |
| 6 | SpotEasy Off-Campus Housing Guide | HTML | https://www.spoteasy.com/blog/how-does-off-campus-housing-near-northeastern-actually-work |
| 7 | NEU Rental Scams Guide | HTML | https://offcampus.housing.northeastern.edu/explore-housing-options/rental-scams/ |
| 8 | Massachusetts Landlord-Tenant Law | HTML | https://www.mass.gov/info-details/massachusetts-law-about-landlord-and-tenant |
| 9 | Boston Broker Fee Guidance | HTML | https://www.boston.gov/departments/housing/office-housing-stability/broker-fees-3-things-know-about-new-law |
| 10 | NEU Housing Megathread (Reddit r/NEU) | Reddit thread | https://www.reddit.com/r/NEU/comments/11eo62e/megathread_please_post_all_housing_and_roommate/ |

> **Note:** Sources 3, 9 (boston.gov), 8 (mass.gov), and 10 (Reddit) block automated requests.

---

## Chunking Strategy

**Chunk size:** 350 tokens (≈ 1,400 characters), estimated at 4 characters per token. The spec called for 300–600 tokens; 350 was chosen after measuring that the midpoint of 450 tokens produced only 45 chunks across 8 documents — below the 50-chunk minimum for meaningful retrieval diversity. Dropping to 350 tokens brought the count to 56 while staying inside the spec range.

**Overlap:** 100 tokens (≈ 400 characters). The chunker drops sentences from the front of the current window until the remaining content fits within 400 characters, which becomes the shared tail of the next chunk. This prevents a key sentence from being cut off at a chunk boundary without duplicating large blocks of text.

**Why these choices fit the documents:** The corpus mixes two content types with very different densities. Legal and policy text (Massachusetts landlord-tenant law, NEU FAQs) contains dense, clause-heavy sentences where a single paragraph can answer a precise question — smaller chunks keep those clauses together. The SpotEasy guide and neighborhood descriptions are narrative and paragraph-structured, so 350-token chunks naturally follow paragraph breaks. 

The chunker splits on sentence boundaries (using a regex that protects abbreviations like `Mr.`, `Dr.`, `vs.`), not on a fixed character count. This means actual chunk sizes vary from 82 to 354 tokens (average 312), but no chunk cuts a sentence in half.

**Preprocessing before chunking:** Each document was fetched and saved raw (HTML/PDF/text), then cleaned in a separate pass: boilerplate tags removed (`<nav>`, `<header>`, `<footer>`, 30+ CSS selectors for cookie banners, sidebars, share buttons), inline link text re-joined into prose, HTML entities decoded, contact-info blocks stripped (phone numbers, addresses, office hours), and orphan lines (nav labels, single-word lines) dropped. The OGS PDF required additional handling: it is a two-column brochure and pdfplumber's default extraction interleaves columns.

**Final chunk count:** 56 chunks across 8 successfully fetched documents.

---

## Embedding Model

**Model used:** `all-MiniLM-L6-v2` via `sentence-transformers`. It was chosen because it is the standard recommendation for small-to-medium retrieval tasks, it has strong performance on semantic similarity benchmarks relative to its size, and local execution means no cost or latency overhead at query time. Vectors are stored in ChromaDB with cosine distance (`hnsw:space: cosine`), which is appropriate for normalized sentence embeddings.

**Production tradeoff reflection:** For a real deployment serving Northeastern students, I would evaluate `text-embedding-3-large` (OpenAI). The main tradeoffs are: (1) **Domain specificity** — Boston housing vocabulary includes terms like "T access," "three-decker," "broker fee," and "tenant-at-will" that are unlikely to be well-represented in general-corpus models; a model trained on legal or real-estate text would embed these more precisely. (2) **Multilingual support** — NEU has a large international student population; a multilingual model like `multilingual-e5-large` would let students query in their first language without translation. (3) **Context length** — `all-MiniLM-L6-v2` has a 256-token limit (inputs are silently truncated beyond that); some policy chunks approach that limit. A model with a longer context window (e.g., `text-embedding-3-large` at 8,192 tokens) would handle those cleanly.

---

## Grounded Generation

**System prompt grounding instruction:**

The system prompt passed to Groq's `llama-3.3-70b-versatile` model reads:

> *"Answer questions using ONLY the information provided in the context documents below. Rules: (1) If the context does not contain enough information to answer the question, respond with exactly: 'I don't have enough information on that based on my sources.' Do NOT guess, infer, or use general knowledge. (2) Keep answers concise — one short paragraph or a brief bulleted list. (3) At the end of every answer, add a 'Sources:' line listing the document name(s) you drew from. (4) If sources give conflicting advice (e.g. a student opinion vs. an official policy), note the conflict briefly rather than picking one side."*

The retrieved chunks are formatted as numbered blocks in the user message:

```
[1] NEU Off-Campus Housing FAQs
<chunk text>

[2] Massachusetts Landlord-Tenant Law
<chunk text>
...
Question: <user question>
Answer only from the context above. Cite sources at the end.
```

In addition to the prompt instruction, a **weak-match guard** in `query.py` checks the cosine distance of the top retrieved chunk before calling Groq. If the best match has a distance above 0.70, the pipeline short-circuits and returns the "not enough information" message without sending any context to the LLM. This prevents the model from receiving low-quality, loosely related context that it might use as a springboard for a plausible-sounding but fabricated answer.

**How source attribution is surfaced in the response:** Attribution is guaranteed at two levels. First, the model is instructed to include a `Sources:` line in its response. Second, `query.py` always appends a `sources` list to the return value, populated directly from chunk metadata — ordered by retrieval rank, deduplicated, and independent of whether the model followed the citation instruction. The Gradio UI displays this `sources` list in a separate "Sources retrieved" box below the answer, so attribution is visible even if the model's in-text citation is imprecise.

---

## Evaluation Report

| # | Question | Expected answer | System response (summarized) | Retrieval quality | Response accuracy |
|---|----------|-----------------|------------------------------|-------------------|-------------------|
| 1 | What housing search tool does Northeastern recommend? | The NU Housing Database / aptsearch portal | Correctly named the Northeastern Housing Database, explained login via Student Hub credentials, mentioned it lists apartments, sublets, roommates, and realtors. | Relevant. Top chunk was the NEU FAQs paragraph that directly answers the question (dist=0.45) | Accurate |
| 2 | What is a common off-campus housing strategy for co-op students? | Look for 4–6 month sublets, since the subletting market is large | Mentioned that co-op students may prioritize "flexibility in lease terms or timing," but did not name sublets specifically or give concrete guidance on length. | Partially relevant: top chunk discussed off-campus housing generally; no chunk specifically addresses co-op sublet strategy because that content lived in the missing Reddit thread | Partially accurate |
| 3 | What commute advice do students give? | Expand searches along the T lines if commuting is possible | Advised students to consider commute time, class schedule, and neighborhood fit when choosing housing. Correctly surfaced T-line proximity from the neighborhoods chunk but framed it as general planning advice, not as a specific student tip. | Partially relevant: chunks about neighborhoods and commute exist but come from official guides, not student voices; dist=0.56 (borderline) | Partially accurate |
| 4 | What social media apps can students use for housing leads? | Facebook groups, Reddit for advice and discussion | Returned "I don't have enough information on that based on my sources." | Off-target — no chunk in the corpus mentions Facebook groups or social media for housing; this content only exists in the Reddit megathread which was unavailable | Inaccurate (correct refusal: the system correctly admitted ignorance rather than hallucinating) |
| 5 | What do students say about broker fees near Northeastern? | Broker fees are common and can equal about one month's rent | Correctly noted that the documents cover the law and regulations around broker fees but do not include student quotes or opinions. Surfaced the 2025 broker fee law change accurately. | Partially relevant: broker fee legal information was retrieved correctly, but student-voice content does not exist in the current corpus | Partially accurate |

---

## Failure Case Analysis

**Question that failed:** *"What is a common off-campus housing strategy for co-op students?"* (Q2)

**What the system returned:** "Some students prefer off-campus housing for its flexibility around co-op schedules. This implies that co-op students may prioritize housing options that offer more flexibility in terms of lease terms or timing." — with no concrete strategy named and no mention of sublets or typical lease lengths.

**Root cause (tied to a specific pipeline stage):**

The failure occurs at two stages compounding each other.

First, at the **document collection stage**: the expected answer ("look for 4–6 month sublets") comes from student-to-student advice in the Reddit megathread, the one source the pipeline could not fetch due to Reddit's API authentication block. The corpus has no substitute for that student-voice content; the closest documents are formal guides (SpotEasy, NEU FAQs) that discuss sublets in general terms but never connect them specifically to co-op students.

Second, at the **retrieval stage**: the query phrase "co-op students" produced poor semantic alignment with the available chunks. The word "co-op" does not appear in any fetched document (SpotEasy and NEU resources use "off-campus housing" generically).

**What you would change to fix it:** The direct fix is improving the data by adding the Reddit megathread, since it contains student posts that explicitly mention co-op timing and sublet length. A structural improvement would be to add a **source-diversity filter** in retrieval: if more than 3 of the top-5 results come from the same source, demote the excess and promote the next-best result from a different document. This would prevent SpotEasy from flooding results on broad queries and surface more specific content from the FAQs or scams guide.

---

## Spec Reflection

**One way the spec helped during implementation:**

The planning.md Chunking Strategy section directly drove a key implementation decision. Although we did not successfully collect Reddit data,  the spec stated that Reddit comments are "short, conversational, and often split across replies," which argued for the lower end of the 300–600 token range. When the initial implementation used 450 tokens (the midpoint) and produced only 45 chunks, the spec gave a principled reason to drop to 350 rather than pick an arbitrary smaller number: 350 stays at the lower end of the stated range and aligns with the rationale written before any code existed. Without that pre-written reasoning, the adjustment would have been a guess. The spec also specified sentence-aware splitting with overlap to "preserve the back-and-forth context in housing threads," which shaped the chunker's design. Because of this, it splits on sentence boundaries and rolls back an overlap window, rather than using a simpler fixed-character split.

**One way the implementation diverged from the spec, and why:**

The architecture diagram in planning.md labels the vector store as **FAISS**. The implementation uses **ChromaDB** instead. The divergence happened because `requirements.txt` (the starter repo provided by the course) already pinned `chromadb>=0.6.0` with no FAISS entry. Rather than install a second vector library, ChromaDB was used throughout — it provides the same ANN search with an easier Python API (no manual index serialization, persistent storage built in, metadata filtering available out of the box). The functional behavior is identical: both use approximate nearest-neighbour search over cosine-distance embeddings. The planning.md diagram was not updated to reflect this because the diagram describes the *logical* pipeline stage, and the stage (Embedding + Vector Store) is unchanged; only the library implementation differs.

---

## AI Usage

**Instance 1 — Ingestion and cleaning pipeline**

- *What I gave the AI:* The Documents section and Chunking Strategy section from planning.md, plus the list of source URLs. I asked Claude to write a script that fetches each source, saves the raw HTML/PDF/text to `documents/raw/`, then cleans each document (remove nav, headers, footers, cookie banners, ads, share buttons, contact blocks) and saves cleaned plain text to `documents/cleaned/`.
- *What it produced:* `load_documents.py` with a `_BOILERPLATE_SELECTORS` list of 30+ CSS selectors, a `_NAV_PHRASES` set for short orphan lines, a `_rejoin_inline_breaks()` function to fix mid-sentence line breaks from inline `<a>` tags, and separate fetch/clean functions per document type (HTML, PDF, Reddit).
- *What I changed or overrode:* Two rounds of correction were needed after inspecting the output. First, the OGS PDF produced garbled text because pdfplumber read a two-column brochure linearly — I directed Claude to add a `_find_column_gap()` function that detects the whitespace gap between columns from the word x0 histogram and extracts each column separately. Second, the broker fee page left a repeated contact block (`Mayor's Office of Housing / 617-635-4200 / 26 Court Street`) that the CSS selectors missed because it was inside `<main>` — I directed Claude to add a `_remove_contact_blocks()` regex pass that strips phone numbers, street addresses, City/ST/ZIP patterns, and known department names.

**Instance 2 — Chunk size calibration**

- *What I gave the AI:* The Chunking Strategy section from planning.md specifying 300–600 tokens and 100–150 token overlap, and the instruction to implement a sentence-aware chunker that reads from `documents/cleaned/` and writes `chunks.json`.
- *What it produced:* `chunk_documents.py` using 450 tokens (the midpoint of 300–600) and 125 tokens overlap. After running it, the output was 45 chunks — below the 50-chunk minimum.
- *What I changed or overrode:* I directed Claude to change `TARGET_TOKENS` from 450 to 350 (the lower end of the spec range) and `OVERLAP_TOKENS` from 125 to 100, and to add a threshold check at the end of the run that prints a warning if the count falls below 50 or above 2,000. I also directed it to update the Chunking Strategy section in planning.md with an explanation of why 450 tokens was rejected and why 350 was chosen — so the spec stays accurate after implementation rather than describing a parameter that wasn't actually used.

**Instance 3 — Debugging retrieval quality**

- *What I gave the AI:* The full retrieval output for all 5 evaluation queries (distance scores, source names, and chunk snippets), and the debugging checklist from the assignment (check distance scores, inspect full chunk content, check metadata, check for HTML leftovers).
- *What it produced:* A systematic inspection script that printed one full chunk per source, the source distribution (chunks per document), distance scores for all 5 queries flagged above 0.65, and a diagnosis identifying SpotEasy's 30% chunk share as a retrieval dominance risk.
- *What I changed or overrode:* The AI initially proposed increasing chunk size to improve Q3/Q4 scores. After reading the full diagnosis, I recognized that Q3/Q4/Q5 weak scores were caused by **missing corpus content** (Reddit), not chunk size. Larger chunks would have hurt precision on queries that do have good coverage (Q1, Q2) without helping the queries that are missing their source. I kept the chunk size at 350 and directed the failure case analysis toward the missing-Reddit root cause instead.
