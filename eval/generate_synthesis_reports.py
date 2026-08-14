"""Generates full research reports for a set of companies, for the
manual synthesis-quality review (project doc Phase 8D). Just generation -
the actual scoring against a rubric is a separate, genuinely manual step
(results/synthesis_quality_review.md), not automated here; this script
only produces the raw material to review.

10 companies, a deliberate mix of section-aware and fallback filings (5
each) so the review isn't accidentally only looking at one chunking
method's output quality.
"""

from __future__ import annotations

import json
from pathlib import Path

from graph.orchestrator import run_research

REPORT_PATH = Path(__file__).resolve().parent.parent / "data" / "eval" / "synthesis_reports.json"

TICKERS = [
    # section_aware
    "AAPL", "JPM", "JNJ", "BA", "VZ",
    # sliding_window_fallback
    "MSFT", "NVDA", "CVX", "F", "PFE",
]

if __name__ == "__main__":
    results = {}
    for ticker in TICKERS:
        print(f"Generating report for {ticker}...")
        state = run_research(ticker, parallel=True)
        results[ticker] = {
            "report": state["synthesis_result"].get("report"),
            "ok": state["synthesis_result"].get("ok"),
            "market_included": state["synthesis_result"].get("market_included"),
            "filings_included": state["synthesis_result"].get("filings_included"),
            "total_latency_seconds": state.get("total_latency_seconds"),
        }
        print(f"  done ({state.get('total_latency_seconds')}s)")

    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(f"\nAll reports written to {REPORT_PATH}")
