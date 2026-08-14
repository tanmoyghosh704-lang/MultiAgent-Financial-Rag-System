"""Latency benchmark (project doc Phase 8C): sequential vs. parallel graph
execution across multiple trials (extends Phase 5's single-pair
measurement with real statistics), and MCP overhead vs. a direct function
call (extends Phase 7's single measurement).

Portable local/Kaggle by construction - every call underneath goes
through Ollama via OLLAMA_HOST (see kaggle/README.md), and this script
itself takes no environment-specific arguments beyond a ticker and trial
count. Run identically in either place:
    python -m eval.latency_bench --trials 3

Kept trial counts modest for local runs (this laptop's numbers are
already known to run 80-130s per graph invocation - see Phase 5's
LOG.md entry) - a proper large-n run belongs on Kaggle, same reasoning
as eval/ragas_eval.py.
"""

from __future__ import annotations

import argparse
import json
import statistics
import time
from pathlib import Path
from typing import Any

from agents.market_agent import fetch_market_data
from graph.orchestrator import run_research
from ingestion.market_data import compute_indicators, fetch_fundamentals, fetch_price_history

REPORT_PATH = Path(__file__).resolve().parent.parent / "data" / "eval" / "latency_report.json"


def benchmark_sequential_vs_parallel(ticker: str, trials: int) -> dict[str, Any]:
    parallel_totals, sequential_totals = [], []
    parallel_details, sequential_details = [], []

    for _ in range(trials):
        r = run_research(ticker, parallel=True)
        parallel_totals.append(r["total_latency_seconds"])
        parallel_details.append(
            {
                "market": r["market_latency_seconds"],
                "filings": r["filings_latency_seconds"],
                "synthesis": r["synthesis_latency_seconds"],
            }
        )

        r = run_research(ticker, parallel=False)
        sequential_totals.append(r["total_latency_seconds"])
        sequential_details.append(
            {
                "market": r["market_latency_seconds"],
                "filings": r["filings_latency_seconds"],
                "synthesis": r["synthesis_latency_seconds"],
            }
        )

    parallel_mean = statistics.mean(parallel_totals)
    sequential_mean = statistics.mean(sequential_totals)

    return {
        "ticker": ticker,
        "trials": trials,
        "parallel_totals": parallel_totals,
        "sequential_totals": sequential_totals,
        "parallel_mean": round(parallel_mean, 2),
        "sequential_mean": round(sequential_mean, 2),
        "parallel_stdev": round(statistics.stdev(parallel_totals), 2) if trials > 1 else 0.0,
        "sequential_stdev": round(statistics.stdev(sequential_totals), 2) if trials > 1 else 0.0,
        "parallel_details": parallel_details,
        "sequential_details": sequential_details,
        "parallel_vs_sequential_pct": round((parallel_mean - sequential_mean) / sequential_mean * 100, 1),
    }


def benchmark_mcp_overhead(ticker: str, trials: int) -> dict[str, Any]:
    mcp_times, direct_times = [], []

    for _ in range(trials):
        t0 = time.time()
        fetch_market_data(ticker)
        mcp_times.append(time.time() - t0)

        t0 = time.time()
        fetch_fundamentals(ticker)
        compute_indicators(fetch_price_history(ticker))
        direct_times.append(time.time() - t0)

    mcp_mean = statistics.mean(mcp_times)
    direct_mean = statistics.mean(direct_times)

    return {
        "ticker": ticker,
        "trials": trials,
        "mcp_times": [round(t, 2) for t in mcp_times],
        "direct_times": [round(t, 2) for t in direct_times],
        "mcp_mean": round(mcp_mean, 2),
        "direct_mean": round(direct_mean, 2),
        "overhead_seconds": round(mcp_mean - direct_mean, 2),
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--ticker", default="F")
    parser.add_argument("--trials", type=int, default=2)
    parser.add_argument("--mcp-trials", type=int, default=5)
    args = parser.parse_args()

    print(f"=== Sequential vs Parallel ({args.trials} trials, ticker={args.ticker}) ===")
    seq_par = benchmark_sequential_vs_parallel(args.ticker, args.trials)
    print(f"Parallel:   mean={seq_par['parallel_mean']}s  stdev={seq_par['parallel_stdev']}  raw={seq_par['parallel_totals']}")
    print(f"Sequential: mean={seq_par['sequential_mean']}s  stdev={seq_par['sequential_stdev']}  raw={seq_par['sequential_totals']}")
    print(f"Parallel vs sequential: {seq_par['parallel_vs_sequential_pct']}% (negative = parallel faster)")

    print(f"\n=== MCP overhead ({args.mcp_trials} trials, ticker={args.ticker}) ===")
    mcp = benchmark_mcp_overhead(args.ticker, args.mcp_trials)
    print(f"MCP call:    mean={mcp['mcp_mean']}s  raw={mcp['mcp_times']}")
    print(f"Direct call: mean={mcp['direct_mean']}s  raw={mcp['direct_times']}")
    print(f"Overhead: {mcp['overhead_seconds']}s")

    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(
        json.dumps({"sequential_vs_parallel": seq_par, "mcp_overhead": mcp}, indent=2), encoding="utf-8"
    )
    print(f"\nReport written to {REPORT_PATH}")
