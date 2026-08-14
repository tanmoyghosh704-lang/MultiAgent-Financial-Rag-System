"""Standalone retrieval sanity test against the built Chroma index.

Run after ingestion/build_index.py. Not a strict correctness test (no
labeled expected-answer set yet — that's the RAGAS test set, Phase 8) —
this just confirms the index is queryable, per-company metadata
filtering works, and section-aware chunks come back with correct
section labels while fallback chunks are honestly labeled "unknown"
rather than a guessed section.
"""

import chromadb
import pytest
from chromadb.utils import embedding_functions

from ingestion.build_index import COLLECTION_NAME, EMBEDDING_MODEL_NAME, INDEX_DIR


@pytest.fixture(scope="module")
def collection():
    client = chromadb.PersistentClient(path=str(INDEX_DIR))
    embedding_fn = embedding_functions.SentenceTransformerEmbeddingFunction(model_name=EMBEDDING_MODEL_NAME)
    return client.get_collection(COLLECTION_NAME, embedding_function=embedding_fn)


def test_index_is_populated(collection):
    assert collection.count() > 0


def test_ticker_filter_returns_only_that_company(collection):
    result = collection.query(
        query_texts=["What are the main risk factors facing the company?"],
        n_results=5,
        where={"ticker": "AAPL"},
    )
    tickers = {m["ticker"] for m in result["metadatas"][0]}
    assert tickers == {"AAPL"}


def test_section_aware_chunk_has_real_section_label(collection):
    result = collection.query(
        query_texts=["What are the main risk factors facing the company?"],
        n_results=3,
        where={"ticker": "AAPL"},  # AAPL is a section_aware filing
    )
    top_meta = result["metadatas"][0][0]
    assert top_meta["method"] == "section_aware"
    assert top_meta["section_item"] == "1A"
    assert "Risk" in top_meta["section_title"]


def test_fallback_chunk_is_honestly_labeled_unknown(collection):
    result = collection.query(
        query_texts=["What are the main risk factors facing the company?"],
        n_results=3,
        where={"ticker": "NVDA"},  # NVDA is a sliding_window_fallback filing
    )
    for meta in result["metadatas"][0]:
        assert meta["method"] == "sliding_window_fallback"
        assert meta["section_item"] == "unknown"


def test_cross_company_semantic_search_surfaces_relevant_company(collection):
    result = collection.query(
        query_texts=["electric vehicle production and battery supply"],
        n_results=5,
    )
    tickers = [m["ticker"] for m in result["metadatas"][0]]
    # Ford is the auto/EV company in the universe - should show up near the top
    # for an EV-specific query even with no ticker filter applied.
    assert "F" in tickers[:3]
