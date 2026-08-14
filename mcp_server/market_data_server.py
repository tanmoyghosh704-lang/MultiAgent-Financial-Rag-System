"""MCP server exposing yfinance-based market-data tools.

Uses the official MCP Python SDK's FastMCP (decorator-based tool
definitions) - checked the actual installed SDK (mcp==1.29.0) via
introspection before writing this, rather than relying on remembered
syntax, per the project doc's explicit warning that this ecosystem
moves fast (`inspect.signature` on `FastMCP.tool`/`FastMCP.run`, and
confirmed `CallToolResult.structuredContent` exists on the client side
for structured dict returns - see LOG.md for what changed between
assumed and actual API shape).

This is a thin protocol adapter, not new business logic: every tool
here wraps a Phase 1 function from `ingestion/market_data.py` unchanged.
Only the Market Agent's tools are exposed via MCP - the Filings Agent's
RAG pipeline deliberately is not (project doc Section 7: no external
consumer, no real decoupling benefit for that pipeline).
"""

from __future__ import annotations

from ingestion.market_data import compute_indicators as _compute_indicators
from ingestion.market_data import fetch_fundamentals, fetch_price_history
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("market-data")


@mcp.tool()
def get_price_history(ticker: str, period: str = "1y") -> dict:
    """Fetch OHLCV price history for a stock ticker (e.g. 'AAPL') over a
    yfinance period string (e.g. '1y', '6mo')."""
    return fetch_price_history(ticker, period)


@mcp.tool()
def get_fundamentals(ticker: str) -> dict:
    """Fetch fundamentals for a stock ticker: trailing P/E, market cap,
    average volume, 52-week price range."""
    return fetch_fundamentals(ticker)


@mcp.tool()
def compute_indicators(ticker: str, period: str = "1y") -> dict:
    """Compute 50/200-day moving averages, annualized realized volatility,
    and recent % change for a stock ticker over a yfinance period string."""
    price_history = fetch_price_history(ticker, period)
    return _compute_indicators(price_history)


if __name__ == "__main__":
    mcp.run()  # defaults to stdio transport
