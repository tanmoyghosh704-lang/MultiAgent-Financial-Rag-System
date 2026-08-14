"""Routing edge-case evaluation (project doc Phase 8B).

Distinct from the pytest suites in graph/test_orchestrator.py and
agents/test_market_agent.py, which already assert on most of these same
cases as part of normal test-driven development (Phases 5 and 7) - this
script exists to produce a standalone, human-readable *report* of routing
behavior as a project deliverable, not to gate a build. Run it directly:
`python -m eval.routing_tests`.

Note on the 5 named scenarios in the project doc ("invalid ticker, valid
ticker with no filings available, both available, both unavailable, MCP
server down"): in this system, "invalid ticker" and "both unavailable"
are the same code path - a ticker with no market data and no filings
produces identical routing behavior regardless of *why* it has no data.
Tested once, not twice, and documented here rather than manufacturing an
artificial second case just to hit a round number of 5.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import agents.market_agent as market_agent_module
from graph.orchestrator import run_research

REPORT_PATH = Path(__file__).resolve().parent.parent / "data" / "eval" / "routing_report.json"


def _summarize(label: str, ticker: str, result: dict[str, Any], expected_route: str) -> dict[str, Any]:
    synthesis = result.get("synthesis_result", {})
    market = result.get("market_result")
    filings = result.get("filings_result")

    market_ok = bool(market and (market["fundamentals"].get("ok") or market["indicators"].get("ok")))
    filings_ok = bool(filings and any(f["result"].get("ok") for f in filings))
    actual_route = "error" if not synthesis.get("ok") and synthesis.get("error") == "no_data_available" else "synthesis"

    return {
        "scenario": label,
        "ticker": ticker,
        "market_ok": market_ok,
        "filings_ok": filings_ok,
        "market_error": None if market_ok else (market["fundamentals"].get("error") if market else None),
        "expected_route": expected_route,
        "actual_route": actual_route,
        "routed_correctly": actual_route == expected_route,
        "synthesis_ok": synthesis.get("ok", False),
    }


def run_routing_evaluation() -> list[dict[str, Any]]:
    results = []

    # 1. Invalid ticker (== "both unavailable" in this system - see module docstring)
    r = run_research("NOTAREALTICKER123", parallel=True)
    results.append(_summarize("invalid_ticker_both_unavailable", "NOTAREALTICKER123", r, expected_route="error"))

    # 2. Valid ticker, no filings available (GOOGL: real yfinance ticker, outside our 15-company index)
    r = run_research("GOOGL", parallel=True)
    results.append(_summarize("valid_ticker_no_filings", "GOOGL", r, expected_route="synthesis"))

    # 3. Both available
    r = run_research("AAPL", parallel=True)
    results.append(_summarize("both_available", "AAPL", r, expected_route="synthesis"))

    # 4. MCP server down (Market Agent's MCP client can't reach the server;
    # Filings Agent is unaffected since it doesn't go through MCP - Section 7)
    original_module = market_agent_module.SERVER_MODULE
    market_agent_module.SERVER_MODULE = "mcp_server.nonexistent_module"
    try:
        r = run_research("AAPL", parallel=True)
    finally:
        market_agent_module.SERVER_MODULE = original_module
    summary = _summarize("mcp_server_down", "AAPL", r, expected_route="synthesis")
    summary["market_error"] = r["market_result"]["fundamentals"].get("error")
    results.append(summary)

    return results


if __name__ == "__main__":
    results = run_routing_evaluation()

    print(f"{'Scenario':<32} {'Ticker':<20} {'Market':<8} {'Filings':<8} {'Route':<10} {'Correct?'}")
    for r in results:
        print(
            f"{r['scenario']:<32} {r['ticker']:<20} "
            f"{'ok' if r['market_ok'] else 'FAIL':<8} {'ok' if r['filings_ok'] else 'FAIL':<8} "
            f"{r['actual_route']:<10} {'OK' if r['routed_correctly'] else 'MISROUTED'}"
        )

    all_correct = all(r["routed_correctly"] for r in results)
    print(f"\nAll scenarios routed correctly: {all_correct}")

    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(f"Report written to {REPORT_PATH}")
