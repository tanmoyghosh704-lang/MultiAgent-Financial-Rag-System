"""Standalone yfinance wrapper functions for the Market Agent.

Plain functions, no MCP and no LangGraph here on purpose — Phase 1 of the
build tests this logic in isolation before it's wrapped by
`mcp_server/market_data_server.py` (Phase 7) and called from a LangGraph
node (Phase 5). Every function returns a small result envelope
(`{"ok": bool, ...}`) instead of raising on a bad ticker, since a
not-found result is a real, expected outcome that the graph's
conditional routing has to branch on later, not an exceptional one.
"""

from __future__ import annotations

from typing import Any

import pandas as pd
import yfinance as yf

DEFAULT_PERIOD = "1y"


def _not_found(ticker: str, detail: str) -> dict[str, Any]:
    return {"ok": False, "ticker": ticker, "error": "ticker_not_found", "detail": detail}


def _ok(ticker: str, data: dict[str, Any]) -> dict[str, Any]:
    return {"ok": True, "ticker": ticker, "data": data}


def fetch_price_history(ticker: str, period: str = DEFAULT_PERIOD) -> dict[str, Any]:
    """Fetch OHLCV price history for `ticker` over `period` (yfinance period string, e.g. '1y', '6mo').

    yfinance does not raise a clean exception for an invalid ticker — it
    returns an empty DataFrame. That emptiness is the actual not-found
    signal checked here.
    """
    t = yf.Ticker(ticker)
    hist = t.history(period=period)
    if hist.empty:
        return _not_found(ticker, f"no price history returned for period={period}")

    records = [
        {
            "date": idx.strftime("%Y-%m-%d"),
            "open": round(float(row["Open"]), 4),
            "high": round(float(row["High"]), 4),
            "low": round(float(row["Low"]), 4),
            "close": round(float(row["Close"]), 4),
            "volume": int(row["Volume"]),
        }
        for idx, row in hist.iterrows()
    ]
    return _ok(ticker, {"period": period, "history": records})


def fetch_fundamentals(ticker: str) -> dict[str, Any]:
    """Fetch fundamentals: trailing P/E, market cap, average volume, 52-week range.

    A dead/invalid ticker still returns an `info` dict from yfinance, just
    with almost every key missing or None. Presence of a name field
    (`shortName`/`longName`) is used as the not-found signal instead of any
    numeric field, since numeric fields being None is also legitimately
    possible for a valid but thinly-covered ticker.
    """
    t = yf.Ticker(ticker)
    info = t.get_info()

    if not info.get("shortName") and not info.get("longName"):
        return _not_found(ticker, "no shortName/longName in yfinance info — ticker likely invalid")

    return _ok(
        ticker,
        {
            "name": info.get("shortName") or info.get("longName"),
            "trailing_pe": info.get("trailingPE"),
            "market_cap": info.get("marketCap"),
            "average_volume": info.get("averageVolume"),
            "fifty_two_week_low": info.get("fiftyTwoWeekLow"),
            "fifty_two_week_high": info.get("fiftyTwoWeekHigh"),
            "currency": info.get("currency"),
        },
    )


def compute_indicators(price_history_result: dict[str, Any]) -> dict[str, Any]:
    """Compute 50/200-day moving averages, annualized realized volatility, and
    recent % change from the envelope returned by `fetch_price_history`.

    Takes the envelope (not a raw DataFrame) so a not-found upstream result
    propagates through unchanged instead of needing a duplicate check at
    every call site.
    """
    if not price_history_result.get("ok"):
        return price_history_result

    ticker = price_history_result["ticker"]
    records = price_history_result["data"]["history"]
    closes = pd.Series([r["close"] for r in records])

    if len(closes) < 2:
        return _not_found(ticker, "not enough price history to compute indicators")

    daily_returns = closes.pct_change().dropna()
    realized_vol = float(daily_returns.std() * (252**0.5)) if len(daily_returns) > 1 else None
    recent_pct_change = float((closes.iloc[-1] - closes.iloc[0]) / closes.iloc[0] * 100)

    ma_50 = float(closes.rolling(50).mean().iloc[-1]) if len(closes) >= 50 else None
    ma_200 = float(closes.rolling(200).mean().iloc[-1]) if len(closes) >= 200 else None

    return _ok(
        ticker,
        {
            "moving_average_50d": round(ma_50, 4) if ma_50 is not None else None,
            "moving_average_200d": round(ma_200, 4) if ma_200 is not None else None,
            "realized_volatility_annualized": round(realized_vol, 6) if realized_vol is not None else None,
            "recent_pct_change": round(recent_pct_change, 4),
            "data_points_used": len(closes),
        },
    )
