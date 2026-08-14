"""Standalone tests for the Synthesis Agent - built with mocked Market/
Filings inputs first, per the project doc's Build Order step 5, before
ever touching the real upstream agents. Fast deterministic tests cover
`check_cross_source_reasoning()`'s logic against fabricated report text;
slower tests make real Ollama calls (7B model - noticeably slower than
the Filings Agent's default light model, expect ~60-100s per call).
"""

from agents.synthesis_agent import _format_market_cap, check_cross_source_reasoning, synthesize_report

MOCK_MARKET = {
    "fundamentals": {
        "ok": True,
        "data": {
            "name": "MockCo Inc.",
            "trailing_pe": 22.5,
            "market_cap": 50_000_000_000,
            "fifty_two_week_low": 80.0,
            "fifty_two_week_high": 145.0,
            "currency": "USD",
        },
    },
    "indicators": {
        "ok": True,
        "data": {
            "moving_average_50d": 138.2,
            "moving_average_200d": 110.5,
            "recent_pct_change": 15.3,
            "realized_volatility_annualized": 0.18,
        },
    },
}

MOCK_FILINGS = [
    {
        "question": "What are the main risk factors disclosed in the filing?",
        "result": {
            "ok": True,
            "answer": (
                "The Company relies on a single customer for approximately 40% of total "
                "revenue (Item 1A). The contract is up for renewal with no guarantee of "
                "renewal on similar terms (Item 1A)."
            ),
        },
    },
]

PASTING_STYLE_REPORT = """## Company Overview
MockCo Inc. is a company.

## Market Snapshot
The stock is up 15.3%.

## Key Risks from Filings
The company depends on one customer for 40% of revenue.

## Market vs. Filings: Agreement or Tension
N/A

## Data Gaps
None.
"""

REASONING_STYLE_REPORT = """## Company Overview
MockCo Inc. is a company.

## Market Snapshot
The stock is up 15.3%.

## Key Risks from Filings
The company depends on one customer for 40% of revenue.

## Market vs. Filings: Agreement or Tension
Despite the recent 15.3% price increase, the filings disclose that revenue growth was driven \
by one customer whose contract is up for renewal. This is a tension: the market's positive \
price movement does not appear to reflect this concentration risk disclosed in the 10-K.

## Data Gaps
None.
"""


def test_format_market_cap_matches_real_jpm_value():
    # Real fetch_fundamentals("JPM") value (verified during Phase 8 manual
    # review) - was reaching the LLM as this raw integer and coming back
    # in generated reports as "$9649.48 billion" (a 10x error) instead of
    # the correct ~$964 billion.
    assert _format_market_cap(964416569344) == "$964.42 billion"


def test_format_market_cap_trillion_scale():
    assert _format_market_cap(4465746247680) == "$4.47 trillion"


def test_check_cross_source_reasoning_flags_pasting_style():
    result = check_cross_source_reasoning(PASTING_STYLE_REPORT)
    assert result["looks_like_reasoning_not_pasting"] is False


def test_check_cross_source_reasoning_passes_real_reasoning():
    result = check_cross_source_reasoning(REASONING_STYLE_REPORT)
    assert result["looks_like_reasoning_not_pasting"] is True
    assert result["missing_headers"] == []


def test_check_cross_source_reasoning_detects_missing_headers():
    incomplete_report = "## Company Overview\nSome text.\n"
    result = check_cross_source_reasoning(incomplete_report)
    assert "Market vs. Filings: Agreement or Tension" in result["missing_headers"]


def test_both_sources_unavailable_returns_structured_error_not_llm_call():
    result = synthesize_report("MOCKCO", None, None)
    assert result["ok"] is False
    assert result["error"] == "no_data_available"


def test_synthesis_with_full_mock_data_reasons_across_sources():
    result = synthesize_report("MOCKCO", MOCK_MARKET, MOCK_FILINGS)
    assert result["ok"] is True
    assert result["market_included"] is True
    assert result["filings_included"] is True
    assert result["reasoning_check"]["missing_headers"] == []


def test_synthesis_with_missing_filings_notes_data_gap():
    result = synthesize_report("MOCKCO", MOCK_MARKET, None)
    assert result["ok"] is True
    assert result["filings_included"] is False
    gaps_section = result["report"].split("Data Gaps")[-1].lower()
    assert "filing" in gaps_section or "not" in gaps_section


def test_synthesis_with_missing_market_notes_data_gap():
    result = synthesize_report("MOCKCO", None, MOCK_FILINGS)
    assert result["ok"] is True
    assert result["market_included"] is False
