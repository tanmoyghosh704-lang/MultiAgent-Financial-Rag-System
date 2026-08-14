"""Embed chunked filings and build a single persistent Chroma collection
with per-chunk company/section metadata - one collection, metadata-filtered
per company at query time (see LOG.md Phase 0 entry for why Chroma was
chosen over FAISS specifically for this).

Run once after ingestion/download_filings.py, before the Filings Agent is
built (Phase 3+). Like the download step, this is ahead-of-time index
building, not something done at query time.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import chromadb
import yaml
from chromadb.utils import embedding_functions

from ingestion.chunker import chunk_filing

REPO_ROOT = Path(__file__).resolve().parent.parent
FILINGS_DIR = REPO_ROOT / "data" / "filings"
INDEX_DIR = REPO_ROOT / "data" / "index"
SOURCES_YAML = REPO_ROOT / "ingestion" / "sources.yaml"

COLLECTION_NAME = "filings"
# Same model used for chunk sizing in chunker.py (MAX_CHUNK_CHARS is sized
# to this model's effective window) - keep them in sync if this changes.
EMBEDDING_MODEL_NAME = "all-MiniLM-L6-v2"

# Chroma's add() has a practical batch-size ceiling; the largest filings
# here (JPM, BAC) run past 1000 chunks, so batch defensively.
BATCH_SIZE = 200


def _load_tickers() -> list[str]:
    with open(SOURCES_YAML, encoding="utf-8") as f:
        return list(yaml.safe_load(f).keys())


def build_index() -> dict[str, Any]:
    INDEX_DIR.mkdir(parents=True, exist_ok=True)
    client = chromadb.PersistentClient(path=str(INDEX_DIR))
    embedding_fn = embedding_functions.SentenceTransformerEmbeddingFunction(model_name=EMBEDDING_MODEL_NAME)

    # Start clean each run so re-running after a chunker change doesn't mix
    # stale chunks in with new ones.
    try:
        client.delete_collection(COLLECTION_NAME)
    except Exception:
        pass
    collection = client.create_collection(name=COLLECTION_NAME, embedding_function=embedding_fn)

    summary: dict[str, Any] = {}
    for ticker in _load_tickers():
        filing_path = FILINGS_DIR / f"{ticker}_10K.htm"
        if not filing_path.exists():
            summary[ticker] = {"ok": False, "error": "filing_not_downloaded"}
            continue

        result = chunk_filing(ticker, filing_path)
        chunks = result["chunks"]

        ids = [f"{ticker}::{c['section_item'] or 'unknown'}::{c['chunk_index']}" for c in chunks]
        documents = [c["text"] for c in chunks]
        metadatas = [
            {
                "ticker": ticker,
                "section_item": c["section_item"] or "unknown",
                "section_title": c["section_title"],
                "chunk_index": c["chunk_index"],
                "method": result["method"],
            }
            for c in chunks
        ]

        for i in range(0, len(ids), BATCH_SIZE):
            collection.add(
                ids=ids[i : i + BATCH_SIZE],
                documents=documents[i : i + BATCH_SIZE],
                metadatas=metadatas[i : i + BATCH_SIZE],
            )

        summary[ticker] = {"ok": True, "method": result["method"], "num_chunks": len(chunks)}

    return summary


if __name__ == "__main__":
    summary = build_index()
    ok = {k: v for k, v in summary.items() if v["ok"]}
    failed = {k: v for k, v in summary.items() if not v["ok"]}

    total_chunks = sum(v["num_chunks"] for v in ok.values())
    print(f"Indexed {len(ok)}/{len(summary)} companies, {total_chunks} chunks total.")
    for ticker, v in ok.items():
        print(f"  {ticker}: {v['num_chunks']} chunks ({v['method']})")
    if failed:
        print("\nFailed:")
        for ticker, v in failed.items():
            print(f"  {ticker}: {v['error']}")
