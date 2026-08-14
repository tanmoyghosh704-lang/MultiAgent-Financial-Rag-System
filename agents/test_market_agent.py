"""Standalone tests for the Market Agent as an MCP client - real round
trips against the actual MCP server subprocess (mcp_server/market_data_server.py),
not a mocked stand-in, since the whole point of this phase is proving the
protocol boundary actually works end to end.
"""

import time

from agents.market_agent import fetch_market_data
from ingestion.market_data import compute_indicators, fetch_fundamentals, fetch_price_history


def test_fetch_market_data_real_round_trip():
    result = fetch_market_data("AAPL")
    assert result["fundamentals"]["ok"] is True
    assert result["indicators"]["ok"] is True
    assert result["fundamentals"]["data"]["name"]
    assert result["indicators"]["data"]["recent_pct_change"] is not None


def test_fetch_market_data_invalid_ticker_propagates_not_found():
    result = fetch_market_data("NOTAREALTICKER123")
    assert result["fundamentals"]["ok"] is False
    assert result["fundamentals"]["error"] == "ticker_not_found"


def test_fetch_market_data_server_unreachable_fails_loudly_no_fallback():
    import agents.market_agent as market_agent_module

    original_module = market_agent_module.SERVER_MODULE
    market_agent_module.SERVER_MODULE = "mcp_server.nonexistent_module"
    try:
        result = market_agent_module.fetch_market_data("AAPL")
    finally:
        market_agent_module.SERVER_MODULE = original_module

    assert result["fundamentals"]["ok"] is False
    assert result["fundamentals"]["error"] == "mcp_server_unreachable"
    assert result["indicators"]["error"] == "mcp_server_unreachable"


def test_mcp_overhead_vs_direct_call():
    """Not a strict pass/fail assertion on the overhead amount - real
    hardware/network variance makes a hard threshold flaky. This exists to
    produce the actual number every test run, the same way Phase 5's
    latency comparison did, rather than asserting the MCP hop is "fast
    enough" without measuring it. See LOG.md for a representative
    measurement and interpretation.
    """
    t0 = time.time()
    fetch_market_data("MSFT")
    mcp_elapsed = time.time() - t0

    t0 = time.time()
    fundamentals = fetch_fundamentals("MSFT")
    indicators = compute_indicators(fetch_price_history("MSFT"))
    direct_elapsed = time.time() - t0

    assert fundamentals["ok"] is True
    assert indicators["ok"] is True
    print(f"\nMCP call: {mcp_elapsed:.2f}s | direct call: {direct_elapsed:.2f}s | "
          f"overhead: {mcp_elapsed - direct_elapsed:.2f}s")
