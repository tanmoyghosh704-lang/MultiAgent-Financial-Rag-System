"""Standalone tests for the Filings Agent - retrieval, generation, and the
grounding check. The grounding-check unit tests use fabricated inputs (no
LLM call, fast and deterministic) since they're testing the check's logic,
not the model's behavior. The end-to-end tests make one real Ollama call
each - slower, but this is exactly the "prove it works standalone before
wiring into the graph" step the project doc asks for at this phase.
"""

from agents.filings_agent import (
    answer_query,
    check_citations_exist,
    check_semantic_grounding,
    retrieve,
)

FAKE_CHUNKS = [
    {"text": "The Company depends on single-source suppliers for certain components.", "section_item": "1A"},
    {"text": "Net sales increased 8% year over year driven by services growth.", "section_item": "7"},
]


def test_retrieve_filters_by_ticker():
    result = retrieve("AAPL", "What are the risk factors?")
    assert result["ok"] is True
    assert all(c["ticker"] == "AAPL" for c in result["chunks"])


def test_check_citations_catches_hallucinated_item():
    # "(Item 9)" was never among the retrieved sections (1A, 7) - this must
    # be flagged as hallucinated, not silently accepted.
    answer = "The company faces supplier risk (Item 1A) and regulatory risk (Item 9)."
    result = check_citations_exist(answer, FAKE_CHUNKS)
    assert result["hallucinated_citations"] == ["9"]
    assert result["all_citations_valid"] is False


def test_check_citations_valid_when_all_cited_items_were_retrieved():
    answer = "The company faces supplier risk (Item 1A)."
    result = check_citations_exist(answer, FAKE_CHUNKS)
    assert result["all_citations_valid"] is True
    assert result["missing_required_citation"] is False


def test_check_citations_flags_missing_citation_on_factual_claim():
    # No (Item X) anywhere, and this isn't a refusal - the citation
    # instruction was simply not followed. This was a real gap found during
    # manual testing (see LOG.md): zero citations trivially has zero
    # *hallucinated* citations too, which without this explicit check would
    # have looked identical to a fully-compliant answer.
    answer = "The company faces supplier risk and regulatory uncertainty."
    result = check_citations_exist(answer, FAKE_CHUNKS)
    assert result["missing_required_citation"] is True
    assert result["all_citations_valid"] is False


def test_check_citations_does_not_flag_explicit_refusal():
    answer = "The provided context does not contain information to answer this question."
    result = check_citations_exist(answer, FAKE_CHUNKS)
    assert result["missing_required_citation"] is False


def test_semantic_grounding_flags_unrelated_sentence():
    answer = "The Company relies on single-source suppliers for some components. The moon is made of cheese."
    result = check_semantic_grounding(answer, FAKE_CHUNKS)
    flagged_text = " ".join(result["flagged_sentences"])
    assert "moon is made of cheese" in flagged_text
    assert "single-source suppliers" not in flagged_text


def test_end_to_end_answer_has_expected_structure():
    result = answer_query("AAPL", "What are the main risk factors related to supply chain?")
    assert result["ok"] is True
    assert isinstance(result["answer"], str) and len(result["answer"]) > 0
    assert "grounding" in result
    assert "citations" in result["grounding"]
    assert "semantic" in result["grounding"]


def test_end_to_end_fallback_ticker_uses_unknown_section_labels():
    # NVDA is a sliding_window_fallback filing (see LOG.md) - retrieved
    # chunks should honestly carry "unknown", never a guessed Item number.
    result = retrieve("NVDA", "What competitive risks does the company face?")
    assert all(c["section_item"] == "unknown" for c in result["chunks"])
