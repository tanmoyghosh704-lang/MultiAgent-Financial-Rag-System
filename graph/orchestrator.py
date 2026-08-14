"""LangGraph orchestrator: wires Market Agent, Filings Agent, and Synthesis
Agent into a real graph with parallel fan-out execution and graph-level
conditional routing.

Two graphs are built from the same nodes - `PARALLEL_GRAPH` (Market and
Filings run concurrently, fan-in to a routing decision) and
`SEQUENTIAL_GRAPH` (Market then Filings then routing) - specifically so
the sequential-vs-parallel latency claim in the project doc's Section 0A
("why multiple agents instead of one ReAct loop") is a real measurement
against identical node logic, not two different implementations that
happen to differ in more ways than just ordering.

The routing after both agents complete is real graph logic (a
`route_after_agents` conditional-edge function evaluated at a shared
join node), not an if-statement buried inside one function - the project
doc is explicit that this distinction is what makes "multi-agent" a
defensible claim rather than a relabeled single function. Note that
`synthesize_report` (Phase 4) *also* has an internal "both sources
unavailable" check of its own - that's not redundant: it's what keeps
the Synthesis Agent correct when called directly/standalone (as Phase 4's
tests do), while this graph-level route additionally avoids invoking the
Synthesis Agent node at all in that case, which matters for the "the
graph should skip agents, not silently no-op inside one" argument.
"""

from __future__ import annotations

import time
from typing import Any

from langgraph.graph import END, START, StateGraph

from agents.filings_agent import answer_query
from agents.synthesis_agent import FILINGS_QUESTIONS, synthesize_report
from graph.state import ResearchState
from ingestion.market_data import compute_indicators, fetch_fundamentals, fetch_price_history


def market_node(state: ResearchState) -> dict[str, Any]:
    t0 = time.time()
    ticker = state["ticker"]
    fundamentals = fetch_fundamentals(ticker)
    price_history = fetch_price_history(ticker)
    indicators = compute_indicators(price_history)
    elapsed = time.time() - t0
    return {
        "market_result": {"fundamentals": fundamentals, "indicators": indicators},
        "market_latency_seconds": round(elapsed, 2),
    }


def filings_node(state: ResearchState) -> dict[str, Any]:
    t0 = time.time()
    ticker = state["ticker"]
    results = [{"question": q, "result": answer_query(ticker, q)} for q in FILINGS_QUESTIONS]
    elapsed = time.time() - t0
    return {"filings_result": results, "filings_latency_seconds": round(elapsed, 2)}


def join_node(state: ResearchState) -> dict[str, Any]:
    # Pass-through - exists only as a fan-in point so route_after_agents
    # evaluates once, after BOTH market_node and filings_node have
    # completed, instead of once per branch.
    return {}


def _market_ok(state: ResearchState) -> bool:
    market = state.get("market_result")
    if not market:
        return False
    return bool(market["fundamentals"].get("ok") or market["indicators"].get("ok"))


def _filings_ok(state: ResearchState) -> bool:
    filings = state.get("filings_result")
    if not filings:
        return False
    return any(f["result"].get("ok") for f in filings)


def route_after_agents(state: ResearchState) -> str:
    if not _market_ok(state) and not _filings_ok(state):
        return "error"
    return "synthesis"


def synthesis_node(state: ResearchState) -> dict[str, Any]:
    t0 = time.time()
    market = state.get("market_result") if _market_ok(state) else None
    filings = state.get("filings_result") if _filings_ok(state) else None
    result = synthesize_report(state["ticker"], market, filings)
    elapsed = time.time() - t0
    return {"synthesis_result": result, "synthesis_latency_seconds": round(elapsed, 2)}


def error_node(state: ResearchState) -> dict[str, Any]:
    return {
        "synthesis_result": {
            "ok": False,
            "ticker": state["ticker"],
            "error": "no_data_available",
            "detail": "Both Market Agent and Filings Agent data are unavailable for this ticker.",
        }
    }


def build_parallel_graph():
    g = StateGraph(ResearchState)
    g.add_node("market", market_node)
    g.add_node("filings", filings_node)
    g.add_node("join", join_node)
    g.add_node("synthesis", synthesis_node)
    g.add_node("error", error_node)

    g.add_edge(START, "market")
    g.add_edge(START, "filings")
    g.add_edge("market", "join")
    g.add_edge("filings", "join")
    g.add_conditional_edges("join", route_after_agents, {"synthesis": "synthesis", "error": "error"})
    g.add_edge("synthesis", END)
    g.add_edge("error", END)
    return g.compile()


def build_sequential_graph():
    g = StateGraph(ResearchState)
    g.add_node("market", market_node)
    g.add_node("filings", filings_node)
    g.add_node("synthesis", synthesis_node)
    g.add_node("error", error_node)

    g.add_edge(START, "market")
    g.add_edge("market", "filings")  # deliberately sequential - filings waits on market despite being independent
    g.add_conditional_edges("filings", route_after_agents, {"synthesis": "synthesis", "error": "error"})
    g.add_edge("synthesis", END)
    g.add_edge("error", END)
    return g.compile()


PARALLEL_GRAPH = build_parallel_graph()
SEQUENTIAL_GRAPH = build_sequential_graph()


def run_research(ticker: str, parallel: bool = True) -> dict[str, Any]:
    graph = PARALLEL_GRAPH if parallel else SEQUENTIAL_GRAPH
    t0 = time.time()
    final_state = graph.invoke({"ticker": ticker})
    total_elapsed = time.time() - t0
    final_state["total_latency_seconds"] = round(total_elapsed, 2)
    final_state["execution_mode"] = "parallel" if parallel else "sequential"
    return final_state
