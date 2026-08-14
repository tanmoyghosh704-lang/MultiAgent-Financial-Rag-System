# Multi-Agent Financial Research Assistant

A multi-agent system (LangGraph + RAG + MCP) that researches a company
the way a junior equity analyst would: pull live market data, dig
through the company's actual annual report, and synthesize both into a
structured report — using multiple specialized agents coordinated by an
orchestrator, not one LLM doing everything in a single prompt.

Full design spec: see the original project doc (multi-agent-financial-research-workflow.md).
Ongoing build decisions and difficulties: [`LOG.md`](LOG.md) — updated
throughout the build, not just at the end. Final distilled writeup (once
complete): `results/writeup.md`.

## Status

Phase 0 (scaffold), Phase 1 (market-data functions), and Phase 2
(filings ingestion: SEC EDGAR download, section-aware chunking,
embedding + Chroma index) — in progress. See `LOG.md` for what's done
and why, including a real pivot (started with Indian companies + manual
PDF sourcing, switched to US companies + SEC EDGAR after the manual
sourcing step proved too slow/unreliable — logged in full).

## Scope

- **Companies:** 15 large-cap US companies across sectors (tech,
  banking, healthcare, consumer staples, energy, industrials, telecom,
  auto) — see `ingestion/sources.yaml` for the list.
- **Filings:** latest 10-K per company, pulled programmatically from SEC
  EDGAR (`ingestion/download_filings.py`), RAG'd with section-aware
  chunking anchored to the standardized Item 1/1A/7/etc. structure
  (`ingestion/chunker.py`), with a documented sliding-window fallback for
  filings where section-heading detection isn't confident.
- **Market data:** yfinance, served via a real MCP server (Market Agent
  is an MCP client, not a direct function caller — see project doc
  Section 0A for why).
- **Orchestration:** LangGraph, with real conditional routing (skip an
  agent whose data isn't available, degrade gracefully rather than
  hallucinate) and parallel execution of the Market and Filings agents.
- **Evaluation:** RAGAS on the filings RAG, routing edge-case tests,
  latency benchmarks (sequential vs parallel, MCP overhead), manual
  synthesis-quality review.

## Compute: local vs Kaggle

Local (Windows laptop, RTX 1650 4GB VRAM) is used for development and
small smoke tests. Batch/heavy jobs (full RAGAS eval, latency
benchmarks, batch synthesis generation) run on Kaggle instead, using
free GPU so the laptop stays free and the run is faster. Every script
reads Ollama host/model config from environment variables so the same
code runs unmodified in either place. See [`kaggle/README.md`](kaggle/README.md)
for the full breakdown and setup steps.

## Setup

```bash
python -m venv .venv
.venv/Scripts/activate      # Windows
pip install -r requirements.txt
cp .env.example .env        # adjust if needed
```

Requires [Ollama](https://ollama.com) running locally with at least
`qwen2.5:7b-instruct-q4_0` and `qwen2.5:1.5b-instruct-q4_0` pulled.

## Repo layout

```
mcp_server/   MCP server exposing yfinance-based market-data tools
agents/       Market Agent (MCP client), Filings Agent (RAG), Synthesis Agent
graph/        LangGraph state + orchestrator (conditional routing, parallel exec)
ingestion/    Market-data functions (Phase 1) + SEC EDGAR download/chunk/index (Phase 2)
data/         Filings, vector index, eval sets (gitignored where regenerable)
eval/         RAGAS eval, routing tests, latency benchmarks
serving/      FastAPI /research endpoint
demo/         Optional Streamlit UI
kaggle/       Portable heavy-compute setup for Kaggle notebooks
results/      Plots, MCP external-client proof, final writeup
```

## Running tests

```bash
pytest ingestion/
```
