# Multi-Agent Financial Research Assistant — Project Writeup

A distilled, interview-ready narrative of what was built and why. The
raw, session-by-session decision log is `LOG.md` — this document is the
polished version, but every claim here traces back to a real dated entry
there with the messy detail (regex iterations, timeout bugs, wrong
numbers found and fixed). When prepping for an interview, skim this
first for the story, then go to `LOG.md` for the specifics if a
follow-up question needs more depth.

---

## 1. What this is

A system that researches a company the way a junior equity analyst
would: pull live market data, read the company's actual SEC filing, and
combine both into one structured report — using **three specialized
agents coordinated by a LangGraph orchestrator**, not one LLM doing
everything in a single prompt. Market data is served through a real
**MCP server**, not called directly, to demonstrate a genuine
tool/agent protocol boundary rather than a decorative one.

**Scope:** 15 large-cap US companies across sectors (tech, banking,
healthcare, consumer staples, energy, industrials, telecom, auto) — see
the table in Section 2. All research is descriptive only; the system
never gives buy/sell advice, by explicit design and system-prompt
instruction.

---

## 2. Data ingestion, in detail

This is the part of the system most worth understanding cold, because
it's where the most concrete, defensible engineering decisions live.

### 2.1 Ticker vs. CIK — two different identifiers

A **ticker** (`AAPL`, `MSFT`) is a stock-exchange trading symbol.
It's what `yfinance` and every retail trading app use — but it is
**not** how the SEC identifies companies, and it can change (companies
rename, re-list, restructure).

A **CIK (Central Index Key)** is the SEC's own permanent numeric ID for
any entity that has ever filed with it. Every company gets exactly one,
for life:

| Company | Ticker | CIK |
|---|---|---|
| Apple | AAPL | 320193 |
| Microsoft | MSFT | 789019 |
| NVIDIA | NVDA | 1045810 |

Why both matter here: `yfinance` (market data) only understands
tickers; SEC's filing-lookup API only understands CIKs. The ingestion
pipeline's first real job is **translating one into the other**.

### 2.2 The three-call chain that resolves "ticker → actual filing text"

Everything is resolved by free, public SEC endpoints — no scraping, no
manual link-hunting, nothing hardcoded:

1. **`www.sec.gov/files/company_tickers.json`** — a single ~13,000-entry
   file mapping every ticker to its CIK. Downloaded once per ingestion
   run.
2. **`data.sec.gov/submissions/CIK{10-digit-padded}.json`** — given a
   CIK, returns the complete filing history for that company. The
   pipeline filters this for `form == "10-K"` and takes the most recent
   one.
3. The actual filing document URL is then fully deterministic:
   `https://www.sec.gov/Archives/edgar/data/{cik}/{accession-number-no-dashes}/{primary-document}`.
   No search step needed — SEC returns the exact filename.

`ingestion/download_filings.py` runs this chain for all 15 companies,
downloads each raw filing to `data/filings/{TICKER}_10K.htm`, and writes
`download_manifest.json` — a small audit record (ticker, CIK, exact URL,
filing date, byte size, success/failure) so every download is traceable
without re-hitting the API. SEC requires a descriptive `User-Agent`
header identifying the requester on every request (their fair-access
policy) — an anonymous one risks throttling.

### 2.3 What a "10-K" actually is, and why that matters for chunking

A **10-K** is the annual report every US public company is legally
required to file. Regulation mandates the same numbered **Items** in
the same order in every single one, regardless of industry:

| Item | Content |
|---|---|
| 1 | Business — what the company does |
| 1A | **Risk Factors** |
| 2 | Properties |
| 3 | Legal Proceedings |
| 7 | **MD&A** — management's narrative on financial results |
| 7A | Market risk disclosures |
| 8 | Financial Statements |
| 9A | Controls and Procedures |
| 10–16 | Governance, compensation, exhibits |

This is *content* structure mandated by law — it says nothing about
*how a given filing agent's HTML renders it*, which turned out to be
the actual difficulty (Section 2.5).

**Why the filings are XHTML, not plain HTML or PDF:** since ~2018, SEC
requires **Inline XBRL (iXBRL)** — every financial figure is tagged
with a machine-readable label, embedded directly in the human-readable
document. Embedding structured XML tags inside a document requires the
whole document to be valid XML — that's exactly what XHTML is. You can
see this in the first line of every downloaded filing:
`<?xml version='1.0' encoding='ASCII'?>` followed by
`<html xmlns:ix="http://www.xbrl.org/2013/inlineXBRL" ...>`.

### 2.4 The pivot: Indian companies → US/SEC EDGAR

The project started with a plan to use 15 Indian companies with
manually-sourced annual report PDFs. After one real attempt at sourcing
those PDFs (delegated to a research agent, which stalled without
producing even one verified URL), the actual cost of that path became
concrete rather than theoretical: no bulk API exists for Indian filings,
every company needs individual manual verification, and there's no
standardized section structure to anchor chunking to. Reconsidered
against the actual goal — the interview-defensibility of this project
comes from the multi-agent architecture and evaluation rigor, not from
which country's companies are in the dataset — and switched to US/SEC
EDGAR, which is fully API-resolvable end to end. This is logged in full
in `LOG.md`'s Phase 2 pivot entry, including the "what I'd do
differently" lesson: validate the riskiest assumption in a data-source
decision with a small spike *before* locking in an architecture around
it, not after building around it.

One casualty of the pivot's own logic, mid-ingestion: **Exxon (XOM)**
turned out to be mid-corporate-reorganization — its ticker now resolves
to a *new* holding-company CIK that had only filed 10-Qs, not a 10-K
yet (a real `8-K12B` filing in its history — the SEC form specifically
used when a new entity becomes successor issuer in a reorg). Rather
than special-case a predecessor-CIK lookup for one company, swapped it
for **Chevron (CVX)** after verifying CVX resolved cleanly. Final
company list:

`AAPL, MSFT, NVDA, JPM, BAC, JNJ, PG, CVX, WMT, KO, BA, VZ, CAT, F, PFE`

### 2.5 Section-aware chunking — and why it isn't one universal regex

**Why not naive fixed-size chunking (e.g. "every 1000 characters"):** a
concrete example from Apple's real filing — a plain 1000-character
window starting mid-document opens with boilerplate about the
investor-relations website (end of Item 1 Business), crosses straight
into Item 1A Risk Factors' opening paragraph, and cuts off mid-word.
That single chunk's embedding would represent a blend of two unrelated
topics, and if retrieved, there'd be no single correct section to cite
it against.

**The actual difficulty:** 10-K *content* structure is standardized by
law, but *HTML rendering* is not — different filing agents (Workiva,
Donnelley, in-house tools) format section headings completely
differently. Two regex heuristics were tried and both failed to
generalize: one matched Apple's non-breaking-space padding convention
perfectly (22/23 real sections) but found **zero** matches on JPMorgan,
Ford, Chevron, or Walmart's filings, because they don't use that
convention. A second, more permissive pattern fixed JPMorgan but broke
worse elsewhere — Ford alone produced 78 false-positive matches, mostly
the phrase "see Item 7" recurring throughout its own MD&A prose (10-Ks
constantly cross-reference their own sections by number, which any
naive pattern-matcher will occasionally mistake for a heading).

**What actually worked:** stop trying to perfect the *pattern*, and
instead resolve ambiguity using *document structure* — walk the 23
canonical Items in their legally-mandated order, and for each one, among
same-numbered candidate matches, pick whichever is followed by the
**longest run of text** before the next Item-like token of any number.
Real section headings are followed by pages of genuine content;
cross-references are usually followed shortly by more ordinary prose.

This recovers a clean, complete section sequence for **7 of 15
filers** (AAPL, JPM, BA, VZ, CAT, JNJ, PG). For the other **8** (MSFT,
NVDA, BAC, CVX, WMT, KO, F, PFE), the heuristic honestly recognizes low
confidence (fewer than 18 of 23 canonical sections recovered) and falls
back to overlapping sliding-window chunks — clearly labeled
`section_item: "unknown"` in the index, not silently guessed. This
fallback-vs-confident split is itself a deliberate design choice: a
single regex forced to be right for every filer would silently
mislabel sections when wrong; a system that knows when it doesn't know
and degrades honestly is more defensible, even though it means only
about half the corpus gets full section-level citation.

Two further real bugs were found only by generating actual answers and
reading the retrieved chunks, not by reading the chunker code:
- The chunk *overlap* logic (carrying the tail of one chunk into the
  next for context continuity) did a raw character-count slice, which
  cut mid-word just as easily as the main splitter did — found because
  a retrieved chunk literally started `"cally with the SEC..."` (cut
  from "specifically").
- `BeautifulSoup.get_text()` has no CSS engine, so it doesn't know
  `display:none` means invisible — it was extracting raw XBRL tag-name
  soup (`us-gaap:CommonStockMember`, bare context IDs) from the hidden
  `<ix:header>` metadata block right alongside real visible prose,
  polluting the first several chunks of every fallback-method filing.
  Fixed by stripping that block before extracting text.

### 2.6 Embedding + vector index

Every chunk (~1200 characters, sized to `sentence-transformers/all-MiniLM-L6-v2`'s
effective ~256-token window — a much larger chunk would have most of
its content silently ignored by the embedding model) is converted into
a 384-dimensional vector and stored in a single **Chroma** collection
with per-chunk metadata (`ticker`, `section_item`, `section_title`,
`method`). Chroma was chosen over FAISS specifically because it
supports metadata `where`-filtering natively at query time — one
collection for all 15 companies, filtered to one company's chunks per
query, with no hand-rolled ID-to-company bookkeeping FAISS would have
needed.

**What "embedding" and "retrieval" actually mean, concretely:** an
embedding model converts text into a list of numbers (a vector) such
that semantically similar text produces nearby vectors. A query like
"what are the risk factors?" gets embedded the same way, and the vector
database finds the stored chunks whose vectors are closest (cosine
similarity) — this is *meaning*-based search, not keyword search. A
real demonstration of this from testing: a query for "electric vehicle
production and battery supply" (no literal keyword overlap with most
filings) correctly surfaced Ford — the one auto/EV company in the
15-company universe — near the top of an *unfiltered* cross-company
search.

**Final numbers:** 7,971 chunks across all 15 companies after the
bug fixes above (was 8,628 before stripping the hidden-metadata
pollution).

---

## 3. Why multiple agents, not one ReAct loop

The interview question this project is built to survive: *"Why did you
need multiple agents instead of one agent with more tools?"*

A single agent (ReAct pattern) is one LLM in a loop: pick a tool,
observe the result, pick the next tool, repeat. The justification for
splitting this into three agents:

1. **Disjoint context budgets.** The Filings Agent operates over
   long-document retrieval; the Market Agent operates over small
   structured JSON. Combining both into one agent's context window
   wastes budget and degrades tool-selection accuracy.
2. **Disjoint tool sets and failure modes** — independently testable,
   independently evaluable, independently swappable (demonstrated
   concretely: Phase 7 replaced the Market Agent's entire data-access
   mechanism, direct function calls → MCP client, with a **one-line
   change** to the orchestrator; nothing else in the system had to
   change).
3. **Market and Filings work is structurally independent** — they can
   run in parallel. A single sequential ReAct loop cannot do that.

Point 3 was built for real (a `PARALLEL_GRAPH` and `SEQUENTIAL_GRAPH`
built from identical node logic) specifically so this argument would
rest on a measured number, not just an assertion — see Section 6 for
what that measurement actually showed, which was **not** what was
expected.

---

## 4. The three agents

### 4.1 Market Agent (`agents/market_agent.py`)

As of Phase 7, an **MCP client** — not a direct function caller. Spawns
`mcp_server/market_data_server.py` as a subprocess over stdio, calls
`get_fundamentals` and `compute_indicators`, parses the JSON results
back into the same shape the rest of the system already expected. If
the MCP server is unreachable, it fails loudly with a structured
`mcp_server_unreachable` error — it never silently falls back to
calling the underlying functions directly, since that would hide a real
operational failure behind what looks like an ordinary not-found
result.

### 4.2 Filings Agent (`agents/filings_agent.py`)

Retrieves top-k chunks (Chroma, filtered by ticker) and generates an
answer via Ollama with **mandatory citation** in `(Item X)` format,
then runs it through **two independent grounding checks**:
- **Citation-existence**: does every cited `(Item X)` actually
  correspond to a section that was retrieved? (catches hallucinated
  *labels*)
- **Semantic grounding**: does every sentence in the answer have a
  retrieved chunk it's actually close to, by embedding similarity?
  (catches hallucinated *content* attached to a real, correctly-cited
  label — something citation-checking alone structurally cannot catch)

A real finding from testing: the default light model
(`qwen2.5:1.5b-instruct-q4_0`) followed the citation format
inconsistently across different questions even with a working prompt
example — sometimes correctly, sometimes not, once answering an
entirely unrelated question instead of declining. Comparing against the
7B model on the same query showed correct behavior but ~2-3x the
latency (~49s vs ~15-25s). Rather than pick a model from a handful of
spot checks, that decision was deliberately deferred to the RAGAS
numbers (Section 6).

### 4.3 Synthesis Agent (`agents/synthesis_agent.py`)

Takes the Market Agent's and Filings Agent's outputs and produces one
5-section markdown report — Company Overview, Market Snapshot, Key
Risks from Filings, **Market vs. Filings: Agreement or Tension**, Data
Gaps — using the 7B model (the one node earmarked for the heaviest
reasoning task). Either input can be `None` (agent skipped/failed
upstream); both `None` short-circuits to a structured error with **no
LLM call at all**.

The doc's core concern for this agent — "a synthesis that just pastes
both sources together is a failed synthesis agent" — is checked by
`check_cross_source_reasoning()`, a cheap heuristic verifying the
Agreement/Tension section has non-trivial length, contains a
connective/comparative word ("however," "despite," "tension," ...),
and mentions terms from *both* sources. This is a proxy, not a proof —
the real answer is the manual review (Section 7).

---

## 5. LangGraph orchestration

`graph/orchestrator.py` builds two `StateGraph`s from identical node
functions:
- **`PARALLEL_GRAPH`**: `START` fans out to `market` and `filings`
  simultaneously, both fan into a `join` node.
- **`SEQUENTIAL_GRAPH`**: `market` → `filings` in sequence.

Routing after both agents complete is **real graph logic** — a
`route_after_agents` function evaluated at the `join` node, wired via
`add_conditional_edges` to either `synthesis` or a dedicated `error`
node — not an if-statement hidden inside one function. This distinction
is what the project doc calls out as the difference between a
defensible "multi-agent" claim and a relabeled single function: the
graph itself decides whether to invoke the LLM-based Synthesis Agent at
all, rather than always calling it and trusting its own internal check.

**Verified routing matrix** (`eval/routing_tests.py`, all correct):

| Scenario | Market | Filings | Route |
|---|---|---|---|
| Invalid ticker | fail | fail | error (no LLM call) |
| Valid ticker, no filings (GOOGL) | ok | fail | synthesis, market-only |
| Both available (AAPL) | ok | ok | synthesis, full report |
| MCP server down | fail | ok | synthesis, filings-only |

---

## 6. MCP integration

**Scope, deliberately limited:** only the Market Agent's tools
(`get_price_history`, `get_fundamentals`, `compute_indicators`) are
exposed via MCP. The Filings Agent's RAG pipeline is **not** — it has
no external consumer, and retrieval over a local index has no real
decoupling benefit from being forced through a protocol boundary. This
scoping decision is itself defensible interview material: MCP is used
where it earns its keep, not applied uniformly because it's the
fashionable choice.

`mcp_server/market_data_server.py` uses the official Python MCP SDK's
`FastMCP` (decorator-based tools). Before writing any client code, the
actual installed SDK (`mcp==1.29.0`) was inspected via
`inspect.signature()` rather than trusting remembered syntax — this
caught a real gap: `CallToolResult.structuredContent` does not
auto-populate for a plain `dict` return type in this version; results
actually come back as `TextContent` with a JSON string body, parsed
with `json.loads`.

**Honest cost side of the tradeoff:** MCP overhead measured at
**2.88 seconds mean** (5 trials) versus a direct function call — almost
entirely subprocess spawn and Python re-import cost, not protocol
serialization. MCP was never going to win on latency against an
in-process call; the benefit is reusability and decoupling, not speed.

**Required external-client proof-of-value:** the project doc requires
demonstrating the same server working with a client outside this
codebase (e.g. Claude Desktop) — this is the step that turns "I used
MCP" into a demonstrated interoperability claim rather than an
assertion. **Not yet completed** as of this writeup — it needs a real
Claude Desktop installation and manual interaction; the exact config and
steps are in `results/mcp_external_client_proof/README.md`, ready to
run in a couple of minutes.

---

## 7. Evaluation results

### 7.1 Routing correctness
All 4 tested scenarios route correctly (Section 5 table).

### 7.2 Latency

| | Parallel | Sequential |
|---|---|---|
| Phase 5 (2 trials) | 129.95s, 105.40s | 109.17s, 91.04s |
| Phase 8 (2 fresh trials) | 134.48s, 90.09s | 100.99s, 95.15s |
| **Mean** | **112.28s** | **98.07s** |

**Parallel execution was ~14.5% slower than sequential** — the opposite
of the expected result, and consistent across 4 independent trials
across two sessions (Phase 5 measured 17.5% slower). This is a genuinely
surprising, honestly-reported finding: it would have been easy to just
assert "parallel is faster" the way most multi-agent write-ups do
without measuring. Root cause: the 7B/1.5B models partially spill to
CPU on this 4GB laptop GPU (a constraint known since Phase 0), so
"parallel" Python threads compete for the same saturated CPU rather
than getting genuine concurrency — LangGraph's thread-based parallelism
only pays off when branches are predominantly I/O-bound with idle CPU
to interleave into, which isn't true here. **This does not invalidate
the multi-agent architectural argument** (Section 3's points 1 and 2
hold independent of this measurement) — it turns "why Kaggle" from a
preemptive plan into a concrete, testable hypothesis: a machine with
real CPU/GPU headroom should show the parallel structure's actual
benefit. Worth re-running this exact comparison on Kaggle to check.

MCP overhead: **2.88s mean** over 5 trials (Section 6).

### 7.3 RAGAS (Filings RAG quality)

30-question test set built (`data/eval/ragas_test_set.json`), pipeline
built and validated locally on a 2-question subset first (per the
project's local/Kaggle compute-split goal — see `kaggle/README.md`),
then run **three times** at full scale: twice on Kaggle GPU (both hit
the `answer_relevancy` bug below), then once locally on the user's own
GPU after root-causing and fixing it. Full scores in
`data/eval/ragas_report.json`.

**Full-scale results, all three runs (n=30 each):**

| Metric | Run 1 (Kaggle) | Run 2 (Kaggle) | Run 3 (local, fixed) |
|---|---|---|---|
| Faithfulness | 0.868 | 0.656 | 0.727 |
| Context Recall | 0.938 | 0.966 | 0.937 |
| Context Precision | 0.269 | 0.218 | 0.218 |
| Answer Relevancy | NaN | NaN | **0.548** |

**Context recall (0.94–0.97) is consistently strong across both runs** —
the retrieved chunks reliably contain what's needed to answer. Safe to
cite as ~0.95.

**Faithfulness ranged 0.656–0.868 across three nominally identical
runs (mean 0.750) — a real, honestly-reported instability, not a
typo.** LLM generation is non-deterministic: the Filings Agent's
answers differ run to run even for the same question and retrieved
context, and that variance is apparently large enough to move a
30-question faithfulness average by ~0.2. Run 3's 0.727 lands between
the first two, which is at least consistent with genuine run-to-run
noise around a real mean rather than a one-directional drift. This
matters for how confidently any single number should be cited — treat
faithfulness as "roughly 0.66–0.87 on this system," not a fixed
constant, until it's been averaged across enough runs to narrow that
range further. (Not done here: each full run costs 20–35 minutes on
Kaggle GPU or ~2.5 hours locally, and running it several more times to
get a tighter estimate was judged not worth the marginal interview
value against the project's remaining scope — a real, named tradeoff,
not an oversight.)

**Context precision (0.22–0.27) is low both times, and honestly
explainable rather than alarming:** this metric specifically scores
*ranking* quality — whether the most relevant retrieved chunk comes
first among the top-k — not whether relevant content exists in the
top-k at all. This system's retrieval is a fixed `k=5` similarity
search with no re-ranking step; a 10-K's table-of-contents or
audit-opinion boilerplate can rank ahead of the actual substantive
passage purely on embedding similarity, even when a genuinely relevant
chunk is also present lower in the same top-5 (which is exactly what
the consistently-high context recall confirms is usually happening).
Low precision alongside high recall and faithfulness is a coherent,
specific signal: retrieval finds the right content, just not always
ranked first — a re-ranking step is the natural next improvement this
points to, not a retrieval failure.

**Answer relevancy: `NaN` for all 30 questions in both Kaggle runs,
root-caused and fixed in Run 3.** This metric has the judge LLM
generate 3 synthetic reverse-questions from each answer, each flagged
`noncommittal` (evasive/vague) or not; the row scores `0.0` if all 3 are
flagged noncommittal, or `NaN` if all 3 come back with unparseable
(empty) structured output. The investigation, in order:
1. **First hypothesis (concurrency, general):** RAGAS's default
   `RunConfig` (`timeout=180s, max_workers=16`) assumes a high-throughput
   remote API; one local Ollama instance can't serve 16 concurrent judge
   calls, so the first local validation attempt failed completely on a
   timeout, every score `NaN`. Fixed with `max_workers=2` — this
   specific timeout bug was real and the fix worked for it.
2. Applied the same reasoning to the full run's `answer_relevancy`
   failure and dropped concurrency further, to `max_workers=1`. **Did
   not fix it** — Run 2 still came back 100% `NaN`.
3. **Second hypothesis (response length/complexity):** tested the exact
   structured-output mechanism in isolation against a realistic long
   multi-point response. Succeeded cleanly. Ruled out.
4. **Third hypothesis (Ollama server-side concurrent-request
   corruption):** traced `ragas`'s source and found `AnswerRelevancy`
   fires its 3 judge calls concurrently, a layer `RunConfig` doesn't
   control. Set `OLLAMA_NUM_PARALLEL=1` to force full server-side
   serialization and re-tested directly (both on Kaggle and, later,
   locally). **Result: zero change** — this disproved the theory
   outright rather than just failing to confirm it, a useful correction
   to an earlier, over-confident write-up of this same hypothesis (see
   `LOG.md` "Phase 8 follow-up 3" vs "follow-up 4").
5. **Actual root cause, found by testing real production data directly:**
   isolated the exact real (freshly-generated) response that was scoring
   `0.0`/`NaN` and ran it through the judge in isolation. All 3 "diverse"
   samples came back byte-identical, and consistently misclassified a
   substantive, well-formed, multi-point bulleted risk-factors answer as
   `noncommittal`. Re-ran the identical test swapping only the judge
   model from `qwen2.5:7b-instruct-q4_0` to `qwen2.5:14b` (already
   available locally): **all 3 samples came back `noncommittal: 0` —
   correct.** Direct, reproducible, before/after proof that the 7B
   quantized judge specifically struggles at this one classification
   sub-task (plausibly pattern-matching "lists several distinct things"
   as "hedging," even though the same model works fine as judge for the
   other 3 metrics).

**Fix:** `AnswerRelevancy` now gets its own stronger judge
(`qwen2.5:14b`), assigned per-metric before the metric list is passed to
RAGAS's `evaluate()` (which only fills in a default judge for metrics
that don't already have one set — confirmed by reading `ragas`'s own
source). The other 3 metrics stay on the faster 7B judge, so this adds
targeted cost only where it was actually needed rather than roughly
doubling the whole run's time.

**Result, confirmed with a real 30-question run:** `answer_relevancy`
mean **0.548**, **zero `NaN` across all 30 rows**. 28 of 30 scored a
real, varied value (0.38–0.96); 2 rows (both the "MD&A trends" question
specifically) still scored `0.0` even with the 14B judge — disclosed
honestly as a residual ~7% error rate, not swept under the rug. This
run took 2h43m on the user's own local GPU (vs. ~20–35 min per run on
Kaggle) — a deliberate trade of speed for full control over every
variable, made after two Kaggle round-trips failed to produce a usable
number.

**A separate real bug, unrelated to RAGAS:** the second Kaggle run's
result-collection step (`kaggle/collect_results.py`) crashed with
`NameError: __file__ not defined` — the script's own docstring had
offered "paste into a cell" as a valid usage option, but `__file__`
isn't defined when code runs as exec'd cell content rather than an
actual script file. Fixed with a `Path.cwd()` fallback and corrected
instructions. No data was lost.

The full trail here — two disproven hypotheses (one initially
mis-attributed with real confidence before being falsified by direct
testing), a significant faithfulness run-to-run variance, a genuinely
root-caused judge-model limitation, and a targeted fix — is reported
plainly rather than smoothed over, consistent with this project's
logging discipline throughout. See `LOG.md`'s four "Phase 8 follow-up"
entries for the full blow-by-blow, including the source-code excerpts
that pinned down the actual mechanism.

### 7.4 Manual synthesis quality review

10 full reports generated and read end-to-end (5 section-aware, 5
fallback filings) — not just scored by the automated heuristic. Full
detail in `results/synthesis_quality_review.md`. Headline finding: this
review **caught a real, confirmed, fixed bug that no automated check
could have found** — 4 of the first 10 reports had market cap figures
wrong by 10x, or (Microsoft) two different values in the same report.
Root cause verified against raw `fetch_fundamentals` data first (always
correct) before assuming the LLM was simply wrong: the bug was handing
the LLM a raw 12-digit integer and trusting it to do billion-scale
division correctly inside its own generated prose. Fixed by
pre-formatting the number before it reaches the prompt at all; verified
live, then all 10 reports regenerated and re-read clean.

Post-fix: 10/10 structurally compliant, 10/10 genuine cross-source
reasoning, 10/10 avoided financial advice, 10/10 correct figures. A
positive, recurring pattern also surfaced: two different fallback-filing
companies, in two different generation runs, both honestly reported "no
risk factors retrievable" instead of fabricating content when retrieval
came back weak — the Phase 2 honesty-over-guessing chunking design
visibly surviving intact all the way through generation and synthesis.

---

## 8. Key decisions, at a glance

| Decision | Alternative considered | Why this one won |
|---|---|---|
| US companies + SEC EDGAR | Indian companies + manual PDFs | Manual PDF sourcing proved slow/unreliable in practice, not just in theory; SEC's API is fully scriptable |
| Chroma over FAISS | FAISS with per-company indices | Native metadata `where`-filtering — no hand-rolled ID bookkeeping |
| Hybrid chunking (section-aware + fallback) | One universal regex | No single pattern generalized across filing agents; honest fallback beats confident wrong labels |
| MCP only for Market Agent | MCP for everything | Filings RAG has no external consumer — MCP there would be decoration, not decoupling |
| Graph-level conditional routing | Routing logic inside `synthesize_report()` | Doc's explicit distinction between real multi-agent routing and a relabeled function |
| Defer Filings Agent model choice (1.5B vs 7B) | Pick one from spot checks | RAGAS numbers are the real evidence; a few examples aren't |
| RAGAS full run on Kaggle, not local | Run 2hrs locally in background | Respects the project's own stated compute-split goal even though background execution was technically possible |

---

## 9. Known limitations (stated honestly, not glossed over)

- **RAGAS answer relevancy**: `NaN` across two full 30-question runs,
  under two different concurrency settings. Two hypotheses tested and
  ruled out (concurrency, response length/complexity); root cause still
  open, likely Kaggle-environment-specific (Section 7.3). Not citable.
- **RAGAS faithfulness has real run-to-run variance**: 0.868 vs. 0.656
  across two full runs of the same 30-question set — cite as a range
  (~0.65–0.87), not a single fixed number, until averaged across more
  runs than was done here (Section 7.3).
- **MCP external-client proof**: not yet completed (needs manual Claude
  Desktop interaction outside this session).
- **Streamlit demo**: startup-verified (both servers run, no errors),
  not click-tested end-to-end in a real browser (no browser automation
  available in this session).
- **Fallback chunking (8/15 companies) scored *higher* mean faithfulness
  than section-aware (7/15) in Run 1** — 0.935 vs. 0.786 (n=16 vs. n=13,
  excluding one corrupted row). Opposite of what the section-aware
  design predicted, and worth reporting rather than dropping quietly —
  but given the faithfulness variance discovered between Run 1 and Run
  2 (0.868 → 0.656 overall), this single-run group comparison is even
  less safe to treat as settled than it looked before that second run:
  the per-group numbers weren't recomputed for Run 2 (only summary
  scores were captured that time), so whether fallback still beats
  section-aware on faithfulness in a second sample is genuinely unknown,
  not just "small sample, be cautious." Also unresolved: the
  section-aware group's Run 1 average was dragged down by one clear
  anomaly (Boeing's risk-factors question scored faithfulness 0.0
  despite containing claims that look traceable to retrieved context on
  manual read).
- **Parallel-vs-sequential result**: real and repeated on this hardware,
  but not yet confirmed to flip on hardware with more headroom (the
  Kaggle re-run that would confirm/deny the CPU-contention hypothesis
  hasn't happened).
- **Numeric narration risk**: the market-cap bug (Section 7.4) is fixed
  for that one field; any other place a raw large number gets handed to
  an LLM for narration is an unaudited instance of the same risk class.

---

## 10. CV bullet

*"Designed a multi-agent financial research assistant using LangGraph,
orchestrating market-data retrieval (served via a custom MCP server),
section-aware SEC-filing RAG with a documented confidence-based
fallback, and cross-source synthesis with conditional routing and
parallel execution; achieved ~0.95 context recall and 0.66-0.87
faithfulness (measured across repeated runs) on a 30-question RAGAS
evaluation harness, and built a manual review process that caught and
fixed a real data-accuracy bug; measured (not assumed) the
sequential-vs-parallel and MCP-vs-direct-call latency tradeoffs on
constrained local hardware."*
