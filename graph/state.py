"""Shared LangGraph state for the research orchestrator.

Market and Filings latency are separate top-level fields, not a shared
dict, on purpose: market_node and filings_node run in the same superstep
in the parallel graph, and LangGraph requires an explicit reducer for any
state key two parallel branches both write to in the same step (a plain
dict field would need `Annotated[dict, some_merge_fn]` or LangGraph
raises an error on the concurrent write). Giving each node its own
top-level key sidesteps that entirely - no reducer needed, and it reads
more clearly than a merged dict of "which node wrote what" anyway.
"""

from __future__ import annotations

from typing import Any, Optional, TypedDict


class ResearchState(TypedDict, total=False):
    ticker: str
    market_result: Optional[dict[str, Any]]
    filings_result: Optional[list[dict[str, Any]]]
    synthesis_result: Optional[dict[str, Any]]
    market_latency_seconds: Optional[float]
    filings_latency_seconds: Optional[float]
    synthesis_latency_seconds: Optional[float]
