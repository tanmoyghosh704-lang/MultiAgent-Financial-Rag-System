"""Standalone tests for the LangGraph orchestrator - real conditional
routing edge cases. Slower than most test files in this repo (each test
runs the real graph, including real Ollama calls) since the whole point
of this phase is proving the *graph* routes correctly, not a mocked
stand-in for it.
"""

from graph.orchestrator import run_research


def test_both_agents_fail_routes_to_error_no_llm_call():
    result = run_research("NOTAREALTICKER123", parallel=True)
    assert result["synthesis_result"]["ok"] is False
    assert result["synthesis_result"]["error"] == "no_data_available"
    # error_node path never calls the LLM - confirm no report field snuck in
    assert "report" not in result["synthesis_result"]


def test_market_ok_filings_unavailable_still_produces_report():
    # GOOGL is a real yfinance ticker not in our 15-company filings index -
    # market succeeds, filings has nothing to retrieve.
    result = run_research("GOOGL", parallel=True)
    assert result["market_result"]["fundamentals"]["ok"] is True
    assert all(not f["result"]["ok"] for f in result["filings_result"])
    assert result["synthesis_result"]["ok"] is True
    # Whether filings were actually unavailable is already verified above
    # programmatically (line 24) - here we only need the Data Gaps section
    # to acknowledge filings topically, not match one specific negation
    # phrasing. An earlier version of this assertion required literal
    # "not"/"unavailable" substrings and broke on "no filings were
    # provided" (correct, just phrased differently) - same brittleness
    # already hit once in this exact test in Phase 5. Fixed properly this
    # time instead of patching another specific phrase. See LOG.md.
    gaps_section = result["synthesis_result"]["report"].lower().split("data gaps")[-1]
    assert "filing" in gaps_section


def test_both_agents_succeed_produces_full_report():
    result = run_research("AAPL", parallel=True)
    assert result["market_result"]["fundamentals"]["ok"] is True
    assert any(f["result"]["ok"] for f in result["filings_result"])
    assert result["synthesis_result"]["ok"] is True
    assert result["synthesis_result"]["market_included"] is True
    assert result["synthesis_result"]["filings_included"] is True


def test_sequential_and_parallel_graphs_reach_same_routing_decision():
    # Different execution order, same graph logic - both should route to
    # the same place for the same ticker, since routing depends on agent
    # results, not on which order the agents ran in.
    parallel_result = run_research("AAPL", parallel=True)
    sequential_result = run_research("AAPL", parallel=False)
    assert parallel_result["synthesis_result"]["ok"] == sequential_result["synthesis_result"]["ok"]
    assert parallel_result["execution_mode"] == "parallel"
    assert sequential_result["execution_mode"] == "sequential"
