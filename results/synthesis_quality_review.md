# Synthesis quality review (project doc Phase 8D)

Manual review of 10 full research reports (Market + Filings + Synthesis,
all real data, no mocks), a deliberate mix of 5 section-aware and 5
sliding-window-fallback filings: AAPL, JPM, JNJ, BA, VZ (section-aware),
MSFT, NVDA, CVX, F, PFE (fallback). Raw reports:
`data/eval/synthesis_reports.json`.

## Rubric

Each report scored against 5 criteria:
1. **Structural compliance** — all 5 required sections present
2. **Cross-source reasoning** — does the "Market vs. Filings" section
   genuinely connect the two data sources, or just restate them
   separately (the project doc's core concern for this agent)
3. **Grounding/accuracy** — are specific numeric claims correct and
   internally consistent (spot-checked against raw `fetch_fundamentals`
   output, not just read for plausibility)
4. **No financial advice** — purely descriptive framing maintained, no
   buy/sell recommendation
5. **Data gaps honesty** — accurately reflects what was/wasn't available,
   doesn't fabricate confidence it doesn't have

## Headline finding: a real, fixable bug caught by this review

**4 of the first 10 reports generated (JPM, VZ, F, MSFT) had wrong or
internally inconsistent market cap figures** — JPM's real market cap
(verified directly against `fetch_fundamentals`, $964.4 billion) was
reported as "$9649.48 billion," a 10x error. MSFT's was reported two
different ways in the *same* report ("$3678 billion" in Company
Overview vs. "$36778 billion" in Market Snapshot).

Root cause, confirmed by checking the raw data first rather than
assuming the LLM was "just wrong": `fetch_fundamentals` was always
correct. The bug was in `agents/synthesis_agent.py::_format_market_context()`,
which handed the LLM a raw integer like `964416569344` and relied on it
to do billion-scale division correctly inside its own generated prose —
exactly the kind of large-number mental arithmetic LLMs are known to be
unreliable at. Fixed by pre-formatting the number
(`_format_market_cap()`) before it ever reaches the prompt, removing the
need for the model to do any conversion at all. Verified against a real
JPM run after the fix: correctly reports "$964.39 billion." Unit-tested
against the real JPM value directly (`agents/test_synthesis_agent.py`).

This is exactly the kind of finding the project doc's Phase 8D exists to
catch — worth stating plainly that it was found by a human (well, an
agent doing a human's job here) actually reading 10 full reports rather
than only checking the automated `check_cross_source_reasoning()`
heuristic, which has no way to catch a wrong number that's otherwise
well-integrated into fluent, well-structured prose.

## Per-company scores (post-fix, regenerated reports)

All 10 reports regenerated after the market-cap fix and re-read in full
- see `data/eval/synthesis_reports.json` for the exact reports this
table reflects.

| Ticker | Method | Structure | Cross-source reasoning | Grounding | No advice | Gaps honesty | Notes |
|---|---|---|---|---|---|---|---|
| AAPL | section_aware | Pass | Pass | Pass | Pass | Pass | Earlier batch had a likely-ungrounded product claim (see below) - not present this run |
| JPM | section_aware | Pass | Pass | Pass ($964.38B, correct) | Pass | Pass | |
| JNJ | section_aware | Pass | Pass | Pass ($627.65B) | Pass | Pass | Cites specific real breakdown (8.4% price, 5.9% volume, 6.0% total sales growth) - strong grounding signal |
| BA | section_aware | Pass | Pass | Pass ($183.07B) | Pass | Pass | |
| VZ | section_aware | Pass | Pass | Pass ($201.61B, correct) | Pass | Pass | Cites specific segment figures ($390M/3.8% Consumer growth, -$462M Business decline) |
| MSFT | fallback | Pass | Pass | Pass ($3.68T, correct & internally consistent) | Pass | Pass | Honestly reports no specific risk factors were retrievable - see pattern note below |
| NVDA | fallback | Pass | Pass | Pass ($5.45T) | Pass | Pass | Comprehensive risk list, clear tension reasoning |
| CVX | fallback | Pass | Pass | Pass ($392.28B, now properly formatted) | Pass | Pass | Connects self-insurance risk specifically to market optimism |
| F | fallback | Pass | Pass (uses subheadings, unusually thorough) | Pass ($57.52B, correct) | Pass | Pass | Honestly notes no P/E ratio was available; see pattern note below |
| PFE | fallback | Pass | Pass | Pass ($152.95B) | Pass | Pass | Cites revenue/cash-flow/EPS figures matching the RAGAS ground truth closely |

**10/10 structurally compliant, 10/10 genuine cross-source reasoning,
10/10 correct market-cap figures post-fix, 10/10 avoided financial
advice.** The one earlier concern (AAPL's possibly-ungrounded product
claim) didn't reproduce in this regenerated run - LLM generation is
non-deterministic, so this doesn't mean the underlying weakness is
gone, just that this specific low-probability detail didn't appear this
time (see below - the RAGAS-measured cause is unchanged).

**Pattern worth flagging: fallback-chunking companies' risk-factor
retrieval sometimes comes back empty/unhelpful, and the system responds
correctly both times it happened here.** Both Ford and Microsoft (both
`sliding_window_fallback` filings) had runs where the risk-factors
question yielded nothing useful, and both times the report explicitly
said so ("the 10-K filing does not provide any specific risk factors,
which is unusual" / "does not explicitly list any risk factors...")
rather than fabricating content. This is the intended behavior
propagating correctly end-to-end: Phase 2 designed the fallback
chunking method to honestly label uncertain sections instead of
guessing, and here that honesty visibly survives all the way through
retrieval, generation, and synthesis instead of getting smoothed over
into false confidence at any layer.

## Specific notes

**AAPL - likely ungrounded claim.** The Company Overview mentions
"expanding its product line with new offerings such as the MacBook Pro
and iPad mini." This is plausible-sounding but suspicious: the Phase 8A
RAGAS run separately found AAPL's MD&A question scored **faithfulness
0.0** - the top retrieved chunks for that question were mostly
table-of-contents and audit-opinion boilerplate, not real MD&A prose
about products (see `data/eval/ragas_report.json` and the LOG.md Phase 8
entry). This specific claim is the kind of content that looks like it
came from the model's general knowledge of Apple rather than the
(poor-quality, for this company/question) retrieved context - two
independent parts of this evaluation (automated RAGAS scoring and
manual reading) converged on the same underlying weakness for the same
company, which is a stronger signal than either alone.

**F (Ford) - honest degradation, observed in the first (pre-fix) batch,
not the regenerated one.** In the first generation of Ford's report
(before the market-cap fix, when Ford's cap was also still wrong), the
Filings section stated "The company's latest SEC filing (10-K) does not
provide any specific risk factors, which is unusual" - a correct,
honest response to genuinely weak retrieval for Ford's risk-factors
question rather than fabricated content. Being explicit that this
observation is from that earlier run, not the currently-saved
regenerated one: Ford's regenerated report (in
`data/eval/synthesis_reports.json` now) got usable risk-factor content
that run and produced real risk content instead. Non-determinism means
the *same underlying retrieval weakness* can surface or not surface
depending on the run, which is also why MSFT's regenerated report
showing the same "no risk factors retrievable" honesty (see the pattern
note above) is the more current, reproducible example of this same good
behavior - two independent observations of it, from two different
companies, across two different batches of this review, not one
company's one-off report.

Also notable from the first Ford batch: that run's MD&A section
mislabeled a 5.9% -> 5.5% adjusted EBIT margin move as an
"improvement" (a real decline) - the exact same error already logged in
Phase 4's testing of this exact company on different data. The
regenerated Ford report doesn't repeat this specific claim at all
(different generation, different content emphasis) - consistent with
this being a real but intermittent generation-quality issue, not a
deterministic bug tied to one number.

## What this review does and doesn't establish

10 companies, one report each per batch (two batches run here, due to
the market-cap fix requiring a redo), is enough to catch categorical
bugs (the market-cap formatting issue) and spot real, recurring
qualitative patterns (honest degradation on weak fallback-filing
retrieval, occasional numeric-directionality errors) across multiple
observed runs - it is not enough to make a statistically confident claim
about synthesis quality overall, and non-determinism means any single
run's specific wording shouldn't be over-indexed on. That's what the
RAGAS numbers (Phase 8A, full run on Kaggle) are for on the
retrieval/generation side; there's no equivalent automated metric for
"is the cross-source reasoning good" beyond the
`check_cross_source_reasoning()` heuristic already built into
`synthesis_agent.py`, which is why this manual pass exists at all.
