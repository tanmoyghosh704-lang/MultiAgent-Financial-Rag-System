"""FastAPI serving layer: POST /research runs the full orchestrator for a
ticker/company name and returns the report plus per-agent metadata (which
agents produced usable data, which were attempted-but-unused, and
per-agent latency) - the project doc's explicit reason for this being
worth building: showing which agents fired and their timings is what
makes the multi-agent architecture visible to someone testing the API,
rather than something they have to take on faith from the code alone.

Endpoint functions are plain `def`, not `async def`: the graph underneath
does blocking I/O (Ollama HTTP calls, yfinance, Chroma) with no async
variant used anywhere in this project, and FastAPI runs sync path
functions in a thread pool automatically - using `async def` here with
blocking calls inside would block the whole event loop instead.
"""

from __future__ import annotations

from typing import Any, Optional

import yaml
from fastapi import FastAPI
from pydantic import BaseModel

from graph.orchestrator import run_research

app = FastAPI(title="Multi-Agent Financial Research Assistant")

SOURCES_YAML = "ingestion/sources.yaml"


def _load_company_universe() -> dict[str, dict[str, Any]]:
    with open(SOURCES_YAML, encoding="utf-8") as f:
        return yaml.safe_load(f)


def resolve_ticker(query: str) -> str:
    """Accept either a ticker or a company name and resolve it to a ticker
    against our 15-company universe. Anything that doesn't match falls
    through unchanged - the graph's own routing (Phase 5) already
    degrades gracefully for an unrecognized ticker, so there's no need
    to reject it here."""
    universe = _load_company_universe()
    query_stripped = query.strip()

    ticker_candidate = query_stripped.upper()
    if ticker_candidate in universe:
        return ticker_candidate

    query_lower = query_stripped.lower()
    for ticker, info in universe.items():
        if query_lower in info["company_name"].lower():
            return ticker

    return ticker_candidate


class ResearchRequest(BaseModel):
    query: str
    parallel: bool = True


class AgentMetadata(BaseModel):
    ok: bool
    latency_seconds: Optional[float]
    used_in_synthesis: bool


class ResearchResponse(BaseModel):
    ticker: str
    ok: bool
    report: Optional[str]
    error: Optional[str]
    execution_mode: str
    total_latency_seconds: float
    market_agent: AgentMetadata
    filings_agent: AgentMetadata
    synthesis_agent: AgentMetadata
    filings_questions_asked: list[str]


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/research", response_model=ResearchResponse)
def research(request: ResearchRequest) -> ResearchResponse:
    ticker = resolve_ticker(request.query)
    state = run_research(ticker, parallel=request.parallel)

    market = state.get("market_result")
    filings = state.get("filings_result")
    synthesis = state.get("synthesis_result", {})

    market_ok = bool(market and (market["fundamentals"].get("ok") or market["indicators"].get("ok")))
    filings_ok = bool(filings and any(f["result"].get("ok") for f in filings))

    return ResearchResponse(
        ticker=ticker,
        ok=synthesis.get("ok", False),
        report=synthesis.get("report"),
        error=synthesis.get("error"),
        execution_mode=state.get("execution_mode", "unknown"),
        total_latency_seconds=state.get("total_latency_seconds", 0.0),
        market_agent=AgentMetadata(
            ok=market_ok,
            latency_seconds=state.get("market_latency_seconds"),
            used_in_synthesis=synthesis.get("market_included", False),
        ),
        filings_agent=AgentMetadata(
            ok=filings_ok,
            latency_seconds=state.get("filings_latency_seconds"),
            used_in_synthesis=synthesis.get("filings_included", False),
        ),
        synthesis_agent=AgentMetadata(
            ok=synthesis.get("ok", False),
            latency_seconds=state.get("synthesis_latency_seconds"),
            used_in_synthesis=True,
        ),
        filings_questions_asked=[f["question"] for f in filings] if filings else [],
    )
