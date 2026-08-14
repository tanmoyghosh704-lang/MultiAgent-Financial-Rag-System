# MCP external-client proof of value

The project doc requires demonstrating the market-data MCP server working
with a client completely outside this project's codebase - this is what
turns "I used MCP" into a demonstrated interoperability claim instead of
an assertion. This step needs your own Claude Desktop installation (or
another MCP-compatible client) - it can't be performed by an agent
working in this terminal-only session, so it's documented here for you
to run and capture.

## Steps

1. Install [Claude Desktop](https://claude.ai/download) if you don't
   already have it.
2. Open its MCP server config file:
   - Windows: `%APPDATA%\Claude\claude_desktop_config.json`
3. Add this server entry (adjust the path if you move the repo):

```json
{
  "mcpServers": {
    "market-data": {
      "command": "C:\\python3_10_11\\MultiAgent Financial Rag System\\.venv\\Scripts\\python.exe",
      "args": ["-m", "mcp_server.market_data_server"],
      "cwd": "C:\\python3_10_11\\MultiAgent Financial Rag System"
    }
  }
}
```

4. Restart Claude Desktop. It should show a 🔌 tools icon indicating the
   `market-data` server connected, exposing three tools:
   `get_price_history`, `get_fundamentals`, `compute_indicators`.
5. In a new chat, ask something like: *"Using the market-data tools,
   what are Apple's fundamentals and 50-day moving average?"* - Claude
   Desktop should call `get_fundamentals` and `compute_indicators` on its
   own and answer using the real data.
6. Save a screenshot of that exchange (showing the tool-call indicator
   and the response) into this folder, e.g. `claude_desktop_proof.png`.

## What this demonstrates

The same server (`mcp_server/market_data_server.py`) that this project's
own Market Agent (`agents/market_agent.py`) talks to is also directly
usable by a completely separate, unrelated application with zero
project-specific code on Claude Desktop's side - only a config entry.
That's the actual decoupling MCP is supposed to buy: one tool
implementation, multiple independent consumers, none of which need to
know about each other or about this project's internals.

## Status

Not yet completed as of the Phase 7 session - flagged in `LOG.md` as an
open item requiring manual action outside this session, not skipped
silently.
