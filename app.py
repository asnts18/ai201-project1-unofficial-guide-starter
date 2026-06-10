"""
app.py — Gradio web interface (Milestone 5)
-------------------------------------------
Run with:  python app.py
Then open: http://localhost:7860

Pipeline (from planning.md architecture diagram):
  User question
      → Retrieval   (ChromaDB + all-MiniLM-L6-v2)
      → Generation  (Groq llama-3.3-70b-versatile)
      → Answer + Sources displayed in UI
"""

import gradio as gr
from query import ask

# ── example questions drawn from planning.md §Evaluation Plan ─────────────────
EXAMPLES = [
    "How much do I need to pay upfront when renting in Boston?",
    "What changed about broker fees in Boston in 2025?",
    "How do I verify an apartment listing isn't a scam?",
    "What neighborhoods near Northeastern have good T access?",
    "Do I need a co-signer for an apartment in Boston?",
    "What is the difference between a lease and a sublet?",
    "How does subletting work at Northeastern?",
    "What should I look for when reading a lease?",
    "What are my rights if my landlord won't make repairs?",
    "What is a tenant-at-will lease?",
]


def handle_query(question: str) -> tuple[str, str, str]:
    """
    Run the full RAG pipeline for one question.
    Returns (answer, sources_text, debug_text) for the three output boxes.
    """
    if not question.strip():
        return "Please enter a question.", "", ""

    result = ask(question)

    answer = result["answer"]

    # Guaranteed source attribution — listed even if LLM omits them
    if result["sources"]:
        sources_text = "\n".join(f"• {s}" for s in result["sources"])
    else:
        sources_text = "No sources retrieved."

    # Debug panel: show top-5 chunk distances so you can inspect retrieval
    debug_lines = []
    for i, chunk in enumerate(result["chunks"], 1):
        snippet = chunk["text"].replace("\n", " ")[:120]
        debug_lines.append(
            f"[{i}] dist={chunk['distance']:.4f}  {chunk['source']}\n    {snippet}…"
        )
    debug_text = "\n\n".join(debug_lines)

    return answer, sources_text, debug_text


# ── UI layout ──────────────────────────────────────────────────────────────────
with gr.Blocks(title="NEU Off-Campus Housing Guide") as demo:

    gr.Markdown(
        """
        # 🏠 NEU Off-Campus Housing — Unofficial Guide
        Ask anything about off-campus housing near Northeastern University in Boston.
        Answers are grounded in official NEU resources, Boston city guidance, and Massachusetts law.
        """
    )

    with gr.Row():
        with gr.Column(scale=3):
            question_box = gr.Textbox(
                label="Your question",
                placeholder="e.g. How much do I need to pay upfront when renting in Boston?",
                lines=2,
            )
            ask_btn = gr.Button("Ask", variant="primary")

        with gr.Column(scale=1):
            gr.Markdown("**Example questions**")
            example_box = gr.Examples(
                examples=[[q] for q in EXAMPLES],
                inputs=question_box,
                label="",
            )

    answer_box = gr.Textbox(
        label="Answer",
        lines=10,
            )

    sources_box = gr.Textbox(
        label="Sources retrieved",
        lines=4,
            )

    with gr.Accordion("🔍 Retrieval debug (chunk distances)", open=False):
        debug_box = gr.Textbox(
            label="Top-5 retrieved chunks",
            lines=14,
                    )

    # Wire up button click and Enter-key submit
    ask_btn.click(
        handle_query,
        inputs=question_box,
        outputs=[answer_box, sources_box, debug_box],
    )
    question_box.submit(
        handle_query,
        inputs=question_box,
        outputs=[answer_box, sources_box, debug_box],
    )

    gr.Markdown(
        """
        ---
        *Answers are based on: NEU Off-Campus Housing resources, Boston.gov guidance,
        Massachusetts landlord-tenant law, and SpotEasy's NEU housing guide.
        Always verify lease terms and legal details with official sources.*
        """
    )


if __name__ == "__main__":
    demo.launch(show_error=True)
