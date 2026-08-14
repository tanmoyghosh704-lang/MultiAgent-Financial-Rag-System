"""Synthesis Agent: combines Market Agent + Filings Agent outputs into one
structured report, reasoning across both sources rather than concatenating
them. Per the project doc, a synthesis that just pastes both sections
together is a failed synthesis agent - that's specifically what
`check_cross_source_reasoning()` in this file exists to catch.

Uses the 7B model (`SYNTHESIS_MODEL`), unlike the Filings Agent's default
1.5B: this is the one node in the whole graph designated for the most
reasoning-heavy step (project doc Section 2), and connecting two
different data sources into one coherent narrative is a harder task than
single-source retrieval+citation.

Plain function, no LangGraph yet - tested standalone first with
deliberately mocked Market/Filings outputs (see test file), per the
project doc's explicit Build Order step 5, before ever being wired to
real upstream agents.
"""

from __future__ import annotations

import os
import re
from typing import Any

import ollama

MODEL_NAME = os.environ.get("SYNTHESIS_MODEL", "qwen2.5:7b-instruct-q4_0")
OLLAMA_KEEP_ALIVE = os.environ.get("OLLAMA_KEEP_ALIVE", "10m")

REQUIRED_SECTIONS = [
    "Company Overview",
    "Market Snapshot",
    "Key Risks from Filings",
    "Market vs. Filings: Agreement or Tension",
    "Data Gaps",
]

# Fixed questions asked of the Filings Agent to gather what the Synthesis
# Agent needs - a real graph node (Phase 5+) would ask exactly these, which
# is why they're pinned here rather than left to whatever caller wanted.
FILINGS_QUESTIONS = [
    "What are the main risk factors disclosed in the filing?",
    "What does management's discussion say about recent financial performance and trends?",
]

SYSTEM_PROMPT = """You are a financial research analyst producing a structured research summary \
by combining market data and filings analysis for one company. This is DESCRIPTIVE RESEARCH \
ONLY - never give a buy/sell recommendation or investment advice; describe what the data shows, \
don't tell the reader what to do with it.

Your report must use exactly these five markdown section headers, in this order:
## Company Overview
## Market Snapshot
## Key Risks from Filings
## Market vs. Filings: Agreement or Tension
## Data Gaps

Critical instruction for "Market vs. Filings: Agreement or Tension": you must explicitly \
connect the two data sources - does the recent price/volatility/fundamentals data seem \
consistent with, or in tension with, what the filings disclose about risks or performance? \
Name a specific connection. Do not just restate each source separately in this section - \
restating both sources without connecting them is a failure, the whole point of this section \
is reasoning ACROSS both sources.

For "Data Gaps": if market data or filings data was unavailable or not provided, say so \
explicitly here. Never invent information for a source that wasn't provided."""

_CONNECTIVE_WORDS = (
    "however", "despite", "while", "although", "in contrast", "consistent with",
    "aligns", "contradicts", "tension", "notably", "unlike", "whereas",
    "on the other hand", "correlates", "reflects", "at odds",
)
_MARKET_TERMS = ("price", "volatility", "moving average", "growth", "%", "market cap", "p/e", "return")
_FILINGS_TERMS = ("risk", "filing", "disclos", "item ", "management", "10-k")


def _format_market_context(market: dict[str, Any] | None) -> str:
    if market is None:
        return "MARKET DATA: not provided (Market Agent was not run for this query)."

    fundamentals = market.get("fundamentals", {})
    indicators = market.get("indicators", {})

    if not fundamentals.get("ok") and not indicators.get("ok"):
        error = fundamentals.get("error") or indicators.get("error") or "unknown error"
        return f"MARKET DATA: unavailable - {error}."

    lines = ["MARKET DATA:"]
    if fundamentals.get("ok"):
        d = fundamentals["data"]
        lines.append(
            f"- {d.get('name', 'Unknown')}: P/E {d.get('trailing_pe')}, "
            f"market cap {d.get('market_cap')}, 52-week range "
            f"{d.get('fifty_two_week_low')}-{d.get('fifty_two_week_high')} {d.get('currency', '')}"
        )
    if indicators.get("ok"):
        d = indicators["data"]
        lines.append(
            f"- 50d MA {d.get('moving_average_50d')}, 200d MA {d.get('moving_average_200d')}, "
            f"recent change {d.get('recent_pct_change')}%, annualized realized volatility "
            f"{d.get('realized_volatility_annualized')}"
        )
    return "\n".join(lines)


def _format_filings_context(filings: list[dict[str, Any]] | None) -> str:
    if filings is None or len(filings) == 0:
        return "FILINGS DATA: not provided (Filings Agent was not run for this query)."

    lines = ["FILINGS DATA (from the company's 10-K):"]
    for item in filings:
        result = item["result"]
        if not result.get("ok"):
            lines.append(f"- Q: {item['question']}\n  A: unavailable ({result.get('error')})")
        else:
            lines.append(f"- Q: {item['question']}\n  A: {result['answer']}")
    return "\n".join(lines)


def synthesize_report(
    ticker: str,
    market: dict[str, Any] | None,
    filings: list[dict[str, Any]] | None,
) -> dict[str, Any]:
    """market: {"fundamentals": <fetch_fundamentals() result>, "indicators": <compute_indicators() result>} or None
    filings: [{"question": str, "result": <filings_agent.answer_query() result>}, ...] or None

    Both None (both agents skipped/failed) returns a structured error
    instead of hallucinating a report - matches the project doc's Section 1
    routing rule: if both agents fail, return a clear structured error.
    """
    market_ok = market is not None and (
        market.get("fundamentals", {}).get("ok") or market.get("indicators", {}).get("ok")
    )
    filings_ok = filings is not None and any(f["result"].get("ok") for f in filings)

    if not market_ok and not filings_ok:
        return {
            "ok": False,
            "ticker": ticker,
            "error": "no_data_available",
            "detail": "Both Market Agent and Filings Agent data are unavailable for this ticker.",
        }

    context = f"{_format_market_context(market)}\n\n{_format_filings_context(filings)}"
    user_prompt = f"Ticker: {ticker}\n\n{context}\n\nProduce the structured report now."

    response = ollama.chat(
        model=MODEL_NAME,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        keep_alive=OLLAMA_KEEP_ALIVE,
    )
    report_text = response["message"]["content"]

    return {
        "ok": True,
        "ticker": ticker,
        "report": report_text,
        "market_included": market_ok,
        "filings_included": filings_ok,
        "reasoning_check": check_cross_source_reasoning(report_text),
    }


def _extract_section(report_text: str, header: str) -> str:
    pattern = re.compile(
        rf"##\s*{re.escape(header)}\s*\n(.*?)(?=\n##|\Z)", re.DOTALL | re.IGNORECASE
    )
    match = pattern.search(report_text)
    return match.group(1).strip() if match else ""


def check_cross_source_reasoning(report_text: str) -> dict[str, Any]:
    """Cheap, automatable proxy for "did this actually reason across
    sources, or just paste them" - checks the Agreement/Tension section
    specifically for: non-trivial length, at least one connective/
    comparative word, and mentions of terms from BOTH sources in the same
    section. Not a proof of good reasoning (a heuristic can be gamed by a
    model that's learned to sprinkle "however" around without meaning it)
    - the real check is Phase 8's manual rubric-scored review across ~10
    companies. This just catches the obvious failure mode (an empty or
    one-line section, or a section that only mentions one source) cheaply,
    on every single run, not just the sampled ones reviewed manually.
    """
    found_headers = [h for h in REQUIRED_SECTIONS if f"## {h}" in report_text or f"##{h}" in report_text]
    missing_headers = [h for h in REQUIRED_SECTIONS if h not in found_headers]

    tension_section = _extract_section(report_text, "Market vs. Filings: Agreement or Tension")
    lowered = tension_section.lower()

    has_connective = any(word in lowered for word in _CONNECTIVE_WORDS)
    has_market_term = any(term in lowered for term in _MARKET_TERMS)
    has_filings_term = any(term in lowered for term in _FILINGS_TERMS)
    non_trivial_length = len(tension_section) > 60

    looks_like_reasoning = has_connective and has_market_term and has_filings_term and non_trivial_length

    return {
        "missing_headers": missing_headers,
        "tension_section_length": len(tension_section),
        "has_connective_language": has_connective,
        "mentions_both_sources": has_market_term and has_filings_term,
        "looks_like_reasoning_not_pasting": looks_like_reasoning,
    }
