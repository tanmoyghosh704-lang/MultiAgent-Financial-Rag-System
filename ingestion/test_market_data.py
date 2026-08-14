"""Standalone tests for the Phase 1 market-data functions.

These hit the real yfinance/Yahoo Finance API on purpose (no mocking) —
the point of this phase is to validate the actual not-found handling and
data shape against real Indian tickers before anything is wrapped in
MCP or LangGraph. Requires internet access.
"""

from ingestion.market_data import compute_indicators, fetch_fundamentals, fetch_price_history

VALID_TICKERS = ["RELIANCE.NS", "TCS.NS"]
INVALID_TICKER = "NOTAREALTICKER123.NS"


def test_fetch_price_history_valid_tickers():
    for ticker in VALID_TICKERS:
        result = fetch_price_history(ticker)
        assert result["ok"] is True
        assert result["ticker"] == ticker
        history = result["data"]["history"]
        assert len(history) > 0
        first = history[0]
        assert {"date", "open", "high", "low", "close", "volume"} <= first.keys()


def test_fetch_price_history_invalid_ticker():
    result = fetch_price_history(INVALID_TICKER)
    assert result["ok"] is False
    assert result["error"] == "ticker_not_found"


def test_fetch_fundamentals_valid_tickers():
    for ticker in VALID_TICKERS:
        result = fetch_fundamentals(ticker)
        assert result["ok"] is True
        data = result["data"]
        assert data["name"]
        assert data["currency"] == "INR"


def test_fetch_fundamentals_invalid_ticker():
    result = fetch_fundamentals(INVALID_TICKER)
    assert result["ok"] is False
    assert result["error"] == "ticker_not_found"


def test_compute_indicators_valid_ticker():
    price_result = fetch_price_history("RELIANCE.NS", period="1y")
    indicators = compute_indicators(price_result)
    assert indicators["ok"] is True
    data = indicators["data"]
    assert data["recent_pct_change"] is not None
    assert data["data_points_used"] > 0
    # 1y of trading days should be enough for a 50d MA but not always 200d
    assert data["moving_average_50d"] is not None


def test_compute_indicators_propagates_not_found():
    price_result = fetch_price_history(INVALID_TICKER)
    indicators = compute_indicators(price_result)
    assert indicators["ok"] is False
    assert indicators["error"] == "ticker_not_found"
