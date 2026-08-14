"""Filings Agent: retrieval + generation over the Chroma index built in
Phase 2, with mandatory source-section citation and a grounding check.

Plain functions, no LangGraph yet - same "prove it works standalone before
wiring into the graph" pattern as Phase 1's market-data functions and
Phase 2's chunker/index. Calls Ollama directly via the `ollama` client
rather than going through MCP: per the project doc (Section 7), the
Filings Agent's RAG pipeline is deliberately NOT exposed via MCP - only
the Market Agent's tools are, since retrieval over a local index has no
external consumer and forcing it through a protocol boundary would be
decoration, not decoupling.
"""

from __future__ import annotations

import os
import re
from typing import Any

import chromadb
import ollama
from chromadb.utils import embedding_functions

from ingestion.build_index import COLLECTION_NAME, EMBEDDING_MODEL_NAME, INDEX_DIR

MODEL_NAME = os.environ.get("LIGHT_MODEL", "qwen2.5:1.5b-instruct-q4_0")
OLLAMA_KEEP_ALIVE = os.environ.get("OLLAMA_KEEP_ALIVE", "10m")

# Below this cosine similarity to its single best-matching retrieved chunk,
# a generated sentence is flagged as not grounded. Calibrated empirically
# (see LOG.md) against real answers, not chosen a priori.
GROUNDING_SIMILARITY_THRESHOLD = 0.35

CITATION_PATTERN = re.compile(r"\(Item\s+(\d{1,2}[A-C]?)\)", re.IGNORECASE)

SYSTEM_PROMPT = """You are a financial research assistant answering questions using ONLY the \
provided excerpts from a company's SEC 10-K filing. Rules:
1. Use only information in the provided context - never use outside knowledge.
2. After every factual claim, cite the section it came from in the exact format (Item X), \
matching one of the section labels shown in the context.
3. If the context does not contain enough information to answer, say so explicitly instead \
of guessing or using outside knowledge.
4. Be concise - a few sentences, not an essay.

Example of the required citation style:
Context contains: [Item 1A - Risk Factors] The Company depends on single-source suppliers \
for some components.
Question: What supplier risk does the company face?
Correct answer: The Company relies on single-source suppliers for certain components, which \
creates supply risk (Item 1A)."""


def _get_collection():
    client = chromadb.PersistentClient(path=str(INDEX_DIR))
    embedding_fn = embedding_functions.SentenceTransformerEmbeddingFunction(model_name=EMBEDDING_MODEL_NAME)
    return client.get_collection(COLLECTION_NAME, embedding_function=embedding_fn), embedding_fn


def retrieve(ticker: str, query: str, k: int = 5) -> dict[str, Any]:
    collection, _ = _get_collection()
    result = collection.query(query_texts=[query], n_results=k, where={"ticker": ticker})

    if not result["documents"][0]:
        return {"ok": False, "error": "no_chunks_found", "ticker": ticker}

    chunks = [
        {"text": doc, **meta}
        for doc, meta in zip(result["documents"][0], result["metadatas"][0])
    ]
    return {"ok": True, "ticker": ticker, "chunks": chunks}


def _build_context_block(chunks: list[dict[str, Any]]) -> str:
    blocks = []
    for c in chunks:
        label = f"Item {c['section_item']}" if c["section_item"] != "unknown" else "Unknown section"
        blocks.append(f"[{label} - {c['section_title']}]\n{c['text']}")
    return "\n\n---\n\n".join(blocks)


def generate_answer(ticker: str, query: str, k: int = 5) -> dict[str, Any]:
    retrieval = retrieve(ticker, query, k=k)
    if not retrieval["ok"]:
        return retrieval

    chunks = retrieval["chunks"]
    context = _build_context_block(chunks)
    user_prompt = f"Context from {ticker}'s 10-K filing:\n\n{context}\n\nQuestion: {query}"

    response = ollama.chat(
        model=MODEL_NAME,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        keep_alive=OLLAMA_KEEP_ALIVE,
    )
    answer_text = response["message"]["content"]

    return {
        "ok": True,
        "ticker": ticker,
        "query": query,
        "answer": answer_text,
        "retrieved_chunks": chunks,
    }


def _split_sentences(text: str) -> list[str]:
    # Good enough for grounding-check purposes - doesn't need to be a full
    # sentence tokenizer, just needs to break the answer into checkable units.
    # Filters out markdown list-marker fragments ("1.", "2.") that a naive
    # split-on-period produces - those have no semantic content of their own
    # and would always score as "ungrounded," which is a splitting artifact,
    # not a real grounding failure (found via a real test run - see LOG.md).
    raw = re.split(r"(?<=[.!?])\s+", text.strip())
    return [s.strip() for s in raw if s.strip() and re.search(r"[a-zA-Z]{3,}", s)]


_REFUSAL_PHRASES = (
    "insufficient information",
    "does not contain",
    "doesn't contain",
    "not contain information",
    "cannot answer",
    "can't answer",
    "no information",
)


def _is_refusal(answer_text: str) -> bool:
    lowered = answer_text.lower()
    return any(phrase in lowered for phrase in _REFUSAL_PHRASES)


def check_citations_exist(answer_text: str, chunks: list[dict[str, Any]]) -> dict[str, Any]:
    """Confirm every (Item X) citation in the answer actually corresponds to
    a retrieved chunk - catches hallucinated citations to sections that
    were never even in context.

    Also tracks whether the answer cited *anything at all*. An answer with
    zero citations trivially has zero hallucinated ones too - "no citations
    contradict the context" is not the same as "this answer is grounded,"
    and treating them as equivalent was a real gap: it let an answer that
    ignored the citation-format instruction entirely still register as
    "all_citations_valid: True." An explicit "I don't know" refusal is the
    one legitimate case where no citation is expected.
    """
    cited_items = {m.group(1).upper() for m in CITATION_PATTERN.finditer(answer_text)}
    retrieved_items = {c["section_item"].upper() for c in chunks if c["section_item"] != "unknown"}

    hallucinated = cited_items - retrieved_items
    missing_required_citation = len(cited_items) == 0 and not _is_refusal(answer_text)

    return {
        "cited_items": sorted(cited_items),
        "retrieved_items": sorted(retrieved_items),
        "hallucinated_citations": sorted(hallucinated),
        "missing_required_citation": missing_required_citation,
        "all_citations_valid": len(hallucinated) == 0 and not missing_required_citation,
    }


def check_semantic_grounding(answer_text: str, chunks: list[dict[str, Any]]) -> dict[str, Any]:
    """For each sentence in the answer, find its cosine similarity to the
    single closest retrieved chunk. Flags sentences that don't look like
    they came from the retrieved context at all - a heuristic, not a proof,
    but a cheap, explainable second signal beyond citation-format checking
    (which only catches hallucinated *labels*, not hallucinated *content*
    attached to a real label)."""
    _, embedding_fn = _get_collection()

    sentences = _split_sentences(answer_text)
    if not sentences:
        return {"sentence_scores": [], "flagged_sentences": []}

    sentence_vecs = embedding_fn(sentences)
    chunk_vecs = embedding_fn([c["text"] for c in chunks])

    def cosine_sim(a, b) -> float:
        dot = sum(x * y for x, y in zip(a, b))
        norm_a = sum(x * x for x in a) ** 0.5
        norm_b = sum(y * y for y in b) ** 0.5
        return dot / (norm_a * norm_b) if norm_a and norm_b else 0.0

    scores = []
    flagged = []
    for sentence, s_vec in zip(sentences, sentence_vecs):
        best = max(cosine_sim(s_vec, c_vec) for c_vec in chunk_vecs)
        scores.append({"sentence": sentence, "max_similarity": round(best, 4)})
        if best < GROUNDING_SIMILARITY_THRESHOLD:
            flagged.append(sentence)

    return {"sentence_scores": scores, "flagged_sentences": flagged}


def answer_query(ticker: str, query: str, k: int = 5) -> dict[str, Any]:
    result = generate_answer(ticker, query, k=k)
    if not result["ok"]:
        return result

    citation_check = check_citations_exist(result["answer"], result["retrieved_chunks"])
    grounding_check = check_semantic_grounding(result["answer"], result["retrieved_chunks"])

    result["grounding"] = {
        "citations": citation_check,
        "semantic": grounding_check,
        "fully_grounded": citation_check["all_citations_valid"] and not grounding_check["flagged_sentences"],
    }
    return result
