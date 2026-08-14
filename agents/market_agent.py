"""Market Agent - as of Phase 7, an MCP client instead of calling
ingestion/market_data.py directly. Connects to
mcp_server/market_data_server.py over stdio: one session spawned per
`fetch_market_data()` call, both tools called within that session, then
torn down. See LOG.md for the measured per-call overhead this adds
versus a direct function call, and why a persistent session wasn't used
instead.

If the MCP server is unreachable (fails to start, crashes, connection
error), this fails loudly with a structured `mcp_server_unreachable`
error - it never silently falls back to calling
`ingestion/market_data.py` directly. Project doc Section 1 is explicit
about this: a silent fallback would hide a real operational failure
behind what looks like an ordinary not-found result, and defeats the
actual point of routing through MCP in the first place.

Tool results come back as MCP `TextContent` with a JSON string body
(`structuredContent` was tested and does not auto-populate for a plain
`dict` return annotation in this SDK version - see LOG.md) - parsed
with `json.loads`, which reconstructs exactly the same
`{"ok": ..., "ticker": ..., ...}` envelope shape `ingestion/market_data.py`
already returns directly, so nothing downstream of this function needed
to change.
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.types import CallToolResult

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SERVER_MODULE = "mcp_server.market_data_server"


def _parse_tool_result(result: CallToolResult) -> dict[str, Any]:
    if result.isError:
        detail = result.content[0].text if result.content else "unknown MCP tool error"
        return {"ok": False, "error": "mcp_tool_error", "detail": detail}
    return json.loads(result.content[0].text)


async def _fetch_market_data_async(ticker: str, period: str) -> dict[str, Any]:
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", SERVER_MODULE],
        cwd=str(PROJECT_ROOT),
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            fundamentals_result = await session.call_tool("get_fundamentals", {"ticker": ticker})
            indicators_result = await session.call_tool(
                "compute_indicators", {"ticker": ticker, "period": period}
            )
            return {
                "fundamentals": _parse_tool_result(fundamentals_result),
                "indicators": _parse_tool_result(indicators_result),
            }


def _describe_error(e: BaseException) -> str:
    """anyio's TaskGroup wraps the real underlying error (e.g. the
    subprocess's "No module named ..." failure) inside nested
    ExceptionGroups, so a bare `str(e)` on the outer exception just says
    "unhandled errors in a TaskGroup" - true, but useless for actually
    diagnosing why the MCP server didn't come up. Recurses into
    `.exceptions` to surface the real leaf cause instead."""
    if hasattr(e, "exceptions") and e.exceptions:
        return _describe_error(e.exceptions[0])
    return f"{type(e).__name__}: {e}"


def fetch_market_data(ticker: str, period: str = "1y") -> dict[str, Any]:
    """MCP-client equivalent of building the market dict directly from
    ingestion/market_data.py (same {"fundamentals": ..., "indicators": ...}
    output shape as Phases 1-6, so graph/orchestrator.py's market_node
    needed a one-line swap, not a redesign - see LOG.md)."""
    try:
        return asyncio.run(_fetch_market_data_async(ticker, period))
    except Exception as e:
        error_detail = _describe_error(e)
        unreachable_error = {"ok": False, "ticker": ticker, "error": "mcp_server_unreachable", "detail": error_detail}
        return {"fundamentals": unreachable_error, "indicators": unreachable_error}
