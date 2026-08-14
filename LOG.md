# Decision & Difficulty Log

This log is maintained in real time throughout the build (not
reconstructed afterward) and is the primary interview-prep artifact for
this project. Every entry follows: what I built, why (with rejected
alternatives), what broke, how it was fixed, what I'd do differently.
`results/writeup.md` will later distill this into a clean narrative, but
this file stays as-is — the raw version is more useful under interview
pressure than the polished summary.

---

## 2026-08-14 — Phase 0: Repo scaffold + environment

### What I built
- Git repo initialized, folder structure per the project spec (`agents/`,
  `graph/`, `mcp_server/`, `ingestion/`, `eval/`, `serving/`, `demo/`,
  `data/`, `results/`), plus a `kaggle/` directory that isn't in the
  original spec — added because of the local/Kaggle compute split
  decided for this build.
- `.venv` created with Python 3.10.11, `requirements.txt` written and
  install kicked off.
- Ollama verified reachable and responsive with `keep_alive` set.
- `kaggle/setup_ollama_kaggle.sh` + `kaggle/README.md` — a portable
  Ollama bootstrap for Kaggle notebooks.

### Why this approach

**Multi-agent justification (why this project exists in this shape at
all):** the whole point of this build is to survive "why not just one
agent with more tools?" A single agent is one LLM in a ReAct loop —
pick a tool, observe, pick the next tool, repeat. That's the wrong shape
here because Market data (small structured JSON from yfinance) and
Filings data (long-document retrieval over annual reports) have
genuinely different context budgets, different tool sets, and different
failure modes, and — most concretely — they don't depend on each other,
so they can run **in parallel**. A sequential ReAct loop can't do that;
a graph with a fan-out/fan-in structure can. This has to be proven with
a measured sequential-vs-parallel latency number later (Phase 5), not
just asserted — noting it here so it isn't forgotten.

**Indian companies via manually-sourced annual report PDFs, not SEC
EDGAR (user decision):** SEC EDGAR is a clean, free, structured API for
10-Ks with predictable `Item 1A` / `Item 7` section boundaries — genuinely
easier to build against. Indian annual reports have no equivalent free,
structured bulk-download API; PDFs have to be sourced from each
company's investor-relations page individually, and section structure
(MD&A, Directors' Report, Corporate Governance Report, financial
statements) is far less consistent between companies. This is a real,
harder version of the ingestion problem — accepted deliberately because
the target roles are India-focused, and "PDF parsing is messier" is
itself honest, defensible interview material rather than a problem to
hide.

**15-company universe, locked now:** RELIANCE.NS, TCS.NS, INFY.NS,
HDFCBANK.NS, ICICIBANK.NS, SBIN.NS, ITC.NS, LT.NS, BHARTIARTL.NS,
HINDUNILVR.NS, WIPRO.NS, TATAMOTORS.NS, ASIANPAINT.NS, MARUTI.NS,
AXISBANK.NS. Chosen for (a) sector diversity (IT, banking, FMCG, auto,
telecom, infra, energy, consumer) so synthesis/eval isn't all testing
the same domain vocabulary, (b) all are large-caps with reliable
`.NS`-suffixed Yahoo Finance coverage, (c) large-caps have stable IR
pages, which matters since PDF sourcing is manual (Phase 2, not yet
done — this is a locked list, not yet verified downloadable).

**ChromaDB over FAISS for the vector store:** the spec calls for
either "one index per company, or one index with company metadata
filtering." Chroma supports metadata `where`-filtering natively at
query time (e.g. filter to one company's chunks inside a single
collection), so the metadata-filtering approach doesn't need any
hand-rolled id→company bookkeeping. FAISS is a lower-level index — it
would work, but filtering by company means either maintaining a
separate FAISS index per company (more moving parts, more index files
to manage) or manually tracking which vector IDs belong to which
company outside the index itself. Chroma's persistence-to-disk +
native filtering removes that bookkeeping, so it was chosen for
developer ergonomics, not because FAISS can't do the job.

**Local dev / Kaggle batch split:** decided in this session (see
`kaggle/README.md` for the full table of what runs where and why). The
mechanism that makes this actually portable rather than "two separate
implementations": every script that talks to Ollama reads
`OLLAMA_HOST` and model names from environment variables
(`.env` / `.env.example`), never hardcodes `localhost`. The exact same
script runs unmodified locally or inside a Kaggle notebook, because in
both cases Ollama is running *inside* that same machine/notebook on
`localhost:11434` — Kaggle isn't being used as a remote inference
server, it's used as a different machine to run the identical local
setup on, with a bigger GPU. This distinction matters for an interview
answer: it's not "call a hosted API instead," it's "run the same local
stack on borrowed hardware."

**Git init:** this wasn't a repo yet (fresh directory). Initialized now
rather than later so the LOG.md narrative can eventually be
cross-referenced against actual commit history if useful during
interview prep.

### Difficulty encountered
None yet at the infrastructure level — Ollama was already set up with
the needed models pulled from prior work (`qwen2.5:0.5b/1.5b/7b-instruct-q4_0`,
plus `qwen2.5:14b` which isn't in the original plan but is available if
a stronger Kaggle-only synthesis pass is ever worth testing later).
`pip install -r requirements.txt` is running in the background as this
entry is being written — will amend/append if it fails on any package
(the ones most likely to need attention on Windows: `chromadb`, which
has native/Rust build dependencies in some versions, and `pymupdf`).

### How it was resolved
N/A yet — see next entry if install issues surface.

### What I'd do differently
Nothing yet to second-guess at this stage — flagging one thing to watch:
the 15-company list was locked based on "should have a stable IR page,"
which is an assumption, not a verified fact. Phase 2 (real PDF sourcing)
is where this gets tested; if 2-3 companies turn out to have unstable or
JS-gated IR pages, the honest move is to swap them out and log why,
not force it.

---

## 2026-08-14 — Phase 0: ragas import bug (real difficulty, good interview material)

### What I built
A workaround module, `eval/_ragas_compat.py`, that must be imported
(specifically its `install_ragas_vertexai_stub()` function called)
before any `import ragas` anywhere in this project.

### Why this approach
Not a design decision so much as damage control — see difficulty below.
The alternative considered and rejected was pinning `ragas==0.3.9`
(a workaround reported on the ragas GitHub issue). Tested it first since
it's the path of least resistance; it did **not** actually fix the
problem in this environment (see below), which is itself a useful
lesson: a workaround reported by someone else may be specific to their
dependency versions, not general — verify before trusting it.

### Difficulty encountered
`python -c "import ragas"` crashed immediately:
```
File ".../ragas/llms/base.py", line 12, in <module>
    from langchain_community.chat_models.vertexai import ChatVertexAI
ModuleNotFoundError: No module named 'langchain_community.chat_models.vertexai'
```
This has nothing to do with anything this project does — it reproduces
on a bare `pip install ragas` in a fresh venv. Root cause (confirmed via
`gh issue view` against `vibrantlabsai/ragas` issues #2741, #2745,
#2753, all open as of 2026-08-14): `langchain-community` moved
`ChatVertexAI` out to a standalone `langchain-google-vertexai` package
and deleted the old `chat_models/vertexai.py` file entirely as part of
its "sunset" deprecation. `ragas/llms/base.py` still does a hard,
unconditional `from langchain_community.chat_models.vertexai import
ChatVertexAI` at import time — so **any** ragas user on a
recent-enough `langchain-community`, whether or not they've ever heard
of Vertex AI, gets a crash just from `import ragas`. This project only
ever talks to Ollama; Vertex AI is irrelevant, but the import still has
to succeed for the package to load at all.

The reported "fix" of pinning `ragas==0.3.9` did not work here — I
tested it directly and got the identical traceback. Reading the actual
issue thread (not just the first search result) showed why: that
workaround was reported by someone on an older `langchain-community`
0.3.x, where the deprecated `vertexai.py` file still physically existed
(just deprecated, with a warning). Our `langchain-community` is 0.4.2,
where the file has been deleted outright — so the ragas version doesn't
matter; the missing module is missing regardless. This is a good
reminder to actually check *why* a workaround worked for someone else
instead of copying it and hoping.

### How it was resolved
Installing `langchain-google-vertexai` (the "correct" modern package)
would **not** have fixed this either — it exposes
`langchain_google_vertexai.ChatVertexAI`, a different dotted path, while
ragas's broken line imports the specific, now-deleted
`langchain_community.chat_models.vertexai` path. No amount of installing
other packages recreates a deleted file.

The actual fix: insert a stub module at that exact dotted path into
`sys.modules` before ragas is ever imported, so Python's import system
finds *something* there instead of raising. The stub's `ChatVertexAI`
class is never instantiated (this project never touches Vertex AI) —
it only has to exist for the `from ... import ChatVertexAI` statement to
succeed. This is `eval/_ragas_compat.py::install_ragas_vertexai_stub()`.
Verified it works with both `ragas==0.3.9` and the latest `ragas==0.4.3`
— since the stub fixes the actual root cause (the missing module),
not a version-specific symptom, there was no reason to stay pinned to
an old ragas. `requirements.txt` now installs latest `ragas` with a
comment pointing at this file.

### What I'd do differently
Would go straight to `gh issue view` on the traceback instead of trying
the first suggested fix from a web search summary first — the summary
text ("Option 1: pin ragas==0.3.9") looked authoritative but was
actually a paraphrase of one issue's workaround section without the
environment caveat that made it not generalize. Reading the primary
source (the actual issue thread) surfaced that caveat immediately.

---

## 2026-08-14 — Phase 1: Market data functions (yfinance wrappers)

### What I built
`ingestion/market_data.py` — three plain functions, no MCP/LangGraph
yet: `fetch_price_history`, `fetch_fundamentals`, `compute_indicators`.
All three return a small `{"ok": bool, ...}` envelope instead of raising
on a bad ticker. `compute_indicators` takes the *envelope* returned by
`fetch_price_history` (not a raw DataFrame) specifically so a
not-found result from the first call propagates through unchanged
instead of needing a duplicate not-found check at every call site —
this is the shape the graph's conditional routing (Phase 5) will branch
on directly. Tests in `ingestion/test_market_data.py` run against real
tickers (`RELIANCE.NS`, `TCS.NS`) and one deliberately invalid ticker —
no mocking, since the point of this phase is validating real API
behavior before wrapping it in anything else.

### Why this approach
yfinance does not raise a clean, catchable exception for an invalid
ticker — `Ticker.history()` returns an empty DataFrame, and
`Ticker.get_info()` returns a dict that's mostly `None`/missing keys but
still a dict, not an error. Detecting "not found" therefore means
checking for emptiness/missing-name rather than catching an exception —
this is the actual reason for the envelope-return design instead of
raising custom exceptions from these functions: the failure mode
yfinance itself uses is "looks like empty/missing data," so representing
it that way (rather than translating it into a Python exception and
back) keeps the not-found signal uniform across all three functions and
directly consumable by graph routing later, without a try/except at
every call site.

For `fetch_fundamentals` specifically, the not-found check uses presence
of `shortName`/`longName` rather than any numeric field (P/E, market
cap, etc.), because numeric fields being `None` is also a legitimate
state for a *valid* but thinly-covered ticker — using a numeric field as
the not-found signal would have produced false "not found" results for
real, valid tickers with sparse fundamentals data.

### Difficulty encountered
None — all 6 tests passed on the first run against real Yahoo Finance
data for `RELIANCE.NS` / `TCS.NS`, and the invalid-ticker case behaved
exactly as expected for both `fetch_price_history` and
`fetch_fundamentals`. Worth recording *that it went cleanly*, since the
project doc specifically calls out yfinance quirks/rate limits as
likely — none showed up in this initial pass with 2 real tickers and a
handful of calls. That's a small sample; rate limiting or data-quality
issues are still plausible once this runs across all 15 companies with
higher call volume (Phase 5+ latency benchmarking), so this isn't a
final verdict — just what was observed with this sample size today.

### How it was resolved
N/A — nothing broke.

### What I'd do differently
Nothing at this scale. Flag for later: once all 15 tickers are hit
repeatedly during latency benchmarking, watch specifically for Yahoo
rate-limiting (`.NS` tickers going through the same Yahoo Finance
backend as US tickers, but request volume during eval runs will be much
higher than this smoke test) and log it if it appears — this is exactly
the kind of "concrete difficulty" material the project doc wants
captured, not smoothed over.

---

## 2026-08-14 — Phase 2 pivot: Indian annual reports → US companies + SEC EDGAR

### What I built
Reversed the Phase 0 decision to use Indian companies + manually-sourced
annual report PDFs. Switching to US companies with filings pulled from
SEC EDGAR instead. New 15-company list and rationale below; the actual
ingestion code follows in the next log entry once built.

### Why this approach
This is a genuine course-correction, not the original plan — worth
logging honestly rather than rewriting history to make it look like US
companies were the plan all along.

What happened: started Phase 2 by trying to source real annual-report
PDF URLs for the 15 Indian companies. Delegated the web research (find
each company's official IR page, locate the direct PDF link) to an
agent. It became clear partway through — and was confirmed by the fact
that the very first attempt at this had to be interrupted before it
even produced a candidate URL for one company — that this was going to
be slow, uncertain, and would need per-company manual verification no
matter what: there's no bulk API, PDF links live behind inconsistent IR
page structures, some are JS-gated, and even a "found" URL isn't
trustworthy until independently downloaded and checked (an agent
reporting a URL is not the same as the URL being real and stable — that
distinction matters and is why every found URL would have needed a real
`curl`/`requests` download to verify before it could go in
`sources.yaml`).

Reconsidered against the actual goal: the interview-defensibility of
this project comes from the multi-agent architecture, real conditional
routing, parallel execution, MCP boundary, and RAGAS evaluation rigor —
none of which depend on which country's companies are in the dataset.
The Indian-companies choice was optimizing for a "more novel / more
relevant to Indian roles" data source at the cost of burning build time
on a brittle, manual ingestion step that has nothing to do with the
actual skills being demonstrated. That's a bad trade once the manual
sourcing cost became concrete instead of theoretical.

**SEC EDGAR, chosen for what it removes, not just what it adds:**
- `www.sec.gov/files/company_tickers.json` — a single free file mapping
  every ticker to its CIK (company identifier). No per-company search.
- `data.sec.gov/submissions/CIK##########.json` — given a CIK, returns
  every filing that company has ever made, so the most recent 10-K can
  be found programmatically (filter `form == "10-K"`, take the most
  recent).
- The actual filing document is then a direct, deterministic URL:
  `https://www.sec.gov/Archives/edgar/data/{cik}/{accession-no-dashes}/{primaryDocument}`.
- End to end: ticker in, filing text out, zero manual URL-hunting, zero
  per-company judgment calls about whether a link is stable.
- 10-Ks have a legally standardized section structure (Item 1, Item 1A
  Risk Factors, Item 7 MD&A, Item 8 Financial Statements, ...) — the
  same headers in the same order for every company, which is what makes
  section-aware chunking (Phase 2's other major design decision) robust
  across all 15 companies with one heuristic, instead of needing
  per-company or best-effort heading detection like the Indian PDFs
  would have required.
- Filings are HTML/plain text, not scanned PDFs — no OCR, no PDF-layout
  extraction quirks (column detection, header/footer noise) to fight.

**Alternative considered and rejected:** keep Indian companies and have
the user manually source the 15 PDFs. Rejected because it shifts the
bottleneck rather than removing it, and still leaves inconsistent
section structure across companies as a standing problem for the
chunking phase — the harder part wasn't just finding URLs, it was
what happens after, with no standardized structure to lean on.

### New company list (replaces the Phase 0 Indian list)

15 large-cap US companies across sectors, chosen for the same reason as
the original list (sector diversity so eval/synthesis isn't testing one
domain's vocabulary) plus SEC EDGAR + yfinance coverage guaranteed for
all of them:

| Company | Ticker | Sector |
|---|---|---|
| Apple | AAPL | Tech/Consumer |
| Microsoft | MSFT | Tech |
| NVIDIA | NVDA | Tech/Semiconductors |
| JPMorgan Chase | JPM | Banking |
| Bank of America | BAC | Banking |
| Johnson & Johnson | JNJ | Healthcare |
| Procter & Gamble | PG | Consumer Staples |
| ExxonMobil | XOM | Energy |
| Walmart | WMT | Retail |
| Coca-Cola | KO | Consumer Staples |
| Boeing | BA | Industrials/Aerospace |
| Verizon | VZ | Telecom |
| Caterpillar | CAT | Industrials |
| Ford | F | Auto |
| Pfizer | PFE | Healthcare/Pharma |

Market data functions from Phase 1 (`ingestion/market_data.py`) need
zero code changes for this switch — they take a ticker string and were
never Indian-market-specific, which validates that keeping them generic
in Phase 1 (rather than, say, hardcoding `.NS` handling anywhere) was
the right call. Only the ticker list and `.env`/config-level company
universe change.

### Difficulty encountered
The interruption itself is the difficulty worth recording: burned real
time and one full agent-research cycle on Indian PDF sourcing before
stepping back and questioning whether the country choice was worth the
cost. The lesson isn't "Indian data is bad" — it's that a data-source
decision made early (Phase 0) without first validating the riskiest
assumption (can PDFs actually be sourced reliably and fast?) cost a
wasted cycle. The fix in the moment: user asked directly "what would be
easy," which is exactly the right question to reset on.

### How it was resolved
Switched data source and company list (this entry). No code from Phase
0/1 needed to change other than the ticker list, since market-data
functions were built ticker-agnostic.

### What I'd do differently
For the next data-source decision in a project like this (if there is
one), validate the riskiest/least-certain assumption first with a small
spike — e.g., before locking in "15 Indian companies, manual PDF
sourcing," try to actually find and download ONE company's PDF first,
timeboxed to a few minutes, before committing the whole company list and
architecture to that path. Would have surfaced this same conclusion in
Phase 0 instead of partway through Phase 2.

---

## 2026-08-14 — Phase 2: SEC EDGAR filing download

### What I built
`ingestion/download_filings.py` — resolves each ticker to a CIK via
SEC's `company_tickers.json`, looks up that CIK's most recent 10-K via
`data.sec.gov/submissions/...`, and downloads the actual filing document
to `data/filings/{TICKER}_10K.htm`. Verified the three-endpoint chain
manually with `curl`/a scratch Python script against AAPL before writing
the real script, rather than writing it against remembered API shape and
hoping. Ran it against all 15 companies; writes a `download_manifest.json`
recording success/failure per ticker for reproducibility.

### Why this approach
Every filing URL is resolved programmatically, nothing hardcoded — this
is the entire point of the Phase 0→2 pivot away from Indian PDFs (see
previous entry): no manual link-hunting, no per-company judgment calls.
SEC requires a descriptive `User-Agent` header with contact info on
every request (their fair-access policy) — used
`"MultiAgent-Financial-RAG-Research tanmoyghosh704@gmail.com"`
consistently; an anonymous/default User-Agent risks throttling or a
block. Added a 0.3s delay between requests — SEC's stated limit is ~10
req/sec, this is a one-time ingestion script so there's no reason to run
anywhere near that limit.

Each function returns a result dict (`{"ok": bool, ...}`) rather than
raising, same pattern as Phase 1's market-data functions — a batch job
over 15 companies should report a full summary at the end, not die on
the first miss.

### Difficulty encountered
1 of 15 companies (XOM — Exxon Mobil) failed with `no_10k_found` on the
first run. Investigated rather than just retrying or skipping it:
`company_tickers.json` maps `XOM` to CIK `2115436`, titled "ExxonMobil
Holdings Corp" — not the long-standing CIK `34088` ("Exxon Mobil Corp")
I'd have expected. Checked that CIK's filing history directly: it has
28 filings, all `10-Q`, `8-K`, `8-K12B`, `S-8 POS`, `POSASR` — no `10-K`
at all. The `8-K12B` form type is the tell: it's specifically used when
a new holding-company entity becomes the successor issuer in a
corporate reorganization. So Exxon appears to be mid-reorg into a new
holding-company structure as of this run, and the new entity hasn't
completed its first annual filing cycle yet — the historical 10-Ks live
under the old, now-superseded CIK.

### How it was resolved
Didn't special-case a predecessor-CIK fallback for one company — that's
exactly the kind of one-off complexity the project doc's time-boxing
section warns against adding. Swapped XOM for Chevron (CVX) instead,
verified CVX resolves to a clean current 10-K first (`curl`-style check
before committing the swap, same discipline as the AAPL verification
above), then re-ran the full batch. All 15/15 downloaded successfully
on the second run.

### What I'd do differently
This is a good, real example of "conditional routing" thinking applied
one level earlier than the graph — the same "does this data source
actually have what I need, and if not, degrade/substitute rather than
force it" judgment the Filings Agent's graph routing will need to make
at query time (Section 1 of the project doc) also applied here at
ingestion time for a company whose expected data wasn't there. Worth
saying explicitly in an interview: this wasn't a bug, it was the
ingestion pipeline correctly surfacing a real-world data-availability
gap, and the fix was a substitution decision, not a code workaround.

---

## 2026-08-14 — Phase 2: Section-aware chunking (and why it isn't universal)

### What I built
`ingestion/chunker.py`: extracts visible text from each filing's HTML
(BeautifulSoup), detects the ~23 standardized 10-K "Item" section
boundaries where possible, and chunks each section to
`MAX_CHUNK_CHARS = 1200` with 150-char overlap, splitting on paragraph
boundaries so a chunk doesn't get cut mid-sentence where avoidable. For
filings where section detection isn't confident (fewer than 18 of the
23 canonical items recovered, in order), falls back to the same
paragraph-aware chunking applied as a sliding window over the whole
document instead. Every chunk records its section item/title (or
`None` + `"unknown (sliding-window fallback)"` for fallback chunks) so
this is visible downstream, not hidden.

Chunk size (1200 chars, 150 overlap) is not arbitrary: sized to
`sentence-transformers/all-MiniLM-L6-v2`'s effective ~256-token window
(roughly 1000-1200 characters of English). A much bigger chunk would
still embed "successfully" but most of its text would be silently
truncated/ignored by the model — the chunk would look fine in the index
but the embedding wouldn't actually represent most of its content. Chose
this over the doc's fixed-size-chunking rejection case for the *inside*
of a section (once you're inside "Item 1A Risk Factors," you still need
to split that section into embeddable pieces — the point is anchoring
those splits to real section boundaries first, not that no
character-count splitting happens anywhere).

**Concrete example of what naive fixed-size chunking would have broken**
(this is the exact kind of evidence the project doc asks for, not just
an assertion): a plain 1000-character window starting at offset 38100 in
Apple's filing produces a chunk that opens mid-sentence with boilerplate
about the investor-relations website (tail end of Item 1 Business),
then crosses straight into Item 1A Risk Factors's opening paragraph, and
gets cut off mid-word: `"...have or have not occurred prev"`
(`previously`, truncated). That single chunk's embedding would represent
a blend of "where to find investor relations info" and "how the company
frames risk disclosures" — two unrelated topics — and if retrieved, the
Filings Agent would have no single correct section to cite it against.
Section-aware chunking's first Risk Factors chunk instead starts cleanly
at `"Item 1A.    Risk Factors\nThe following summarizes factors..."`
with a real section label attached.

### Why this approach (regex iteration - the real story, not the clean version)
First heuristic: match `Item\s+(\d+[A-C]?)\.` followed by 2+ literal
non-breaking spaces (`\xa0\xa0`) then a title on the same line — this
was based on how Apple's filing (Workiva-rendered) visually pads
headings with repeated `&nbsp;` for indentation, cleanly distinguishing
real headings (nbsp-padded) from table-of-contents entries (newline-
separated, no padding) and body cross-references (no trailing period).
Worked perfectly on Apple: 22/23 correct sections, zero false
positives. Tested against 6 more filers before trusting it — JPM, WMT,
F, CVX all returned **zero** matches. Different filing agents don't use
the nbsp-padding convention at all.

Second heuristic: relaxed the separator to any non-newline whitespace
(`[ \t\xa0]+`) with the title ending in an optional period before a
newline, based on how JPM's filing actually renders headings
(`"Item 1A. Risk Factors. \nThe following..."`). This recovered JPM
cleanly (21 sections) but was *worse* elsewhere: F jumped to 78 matches
(mostly the word "Item 7" recurring throughout the MD&A section's own
running prose, e.g. "...as discussed in Item 7...", which happens
constantly in real 10-Ks because sections cross-reference each other
by Item number) and MSFT still matched nothing.

### Difficulty encountered
The core problem neither regex actually solved: cross-references to
other Items are a *structural* feature of 10-K prose, not noise to
filter with a slightly better pattern — MD&A sections routinely say
"see Item 7A" or "as described in Item 1A," and any purely pattern-based
heading matcher will occasionally mistake one of these for a real
heading, especially at scale across 15 different filing agents' HTML
conventions. There is no single regex that cleanly separates "this text
looks like a heading" from "this text mentions an Item number in a
sentence" — both can be arbitrarily similar depending on how a given
filing agent's HTML happens to wrap and format.

### How it was resolved
Stopped trying to fix this with a better pattern and changed the
*decision procedure* instead: keep the broad, permissive candidate
regex (catches real headings AND false positives), but resolve
ambiguity using document structure rather than text formatting —
walk the 23 canonical items in their legally-mandated order, and for
each one, among same-numbered candidates after the previous accepted
section, pick whichever is followed by the **longest run of text**
before the next Item-like token of any number. Real section headings
are followed by pages of genuine content; an inline cross-reference is
usually followed shortly by more ordinary prose (which often mentions
another Item number soon after, in the same paragraph or the next).
This is a heuristic, not a guarantee — it recovered a clean full
sequence for 7/15 filers (AAPL, JPM, BA, VZ, CAT, JNJ, PG) and
correctly self-identified low confidence for the other 8 (MSFT, NVDA,
BAC, CVX, WMT, KO, F, PFE all landed below the 18-section threshold),
which is exactly the honest outcome wanted here: rather than force a
single regex to be right for everyone (and silently mislabel sections
when it's wrong), the chunker knows when it doesn't know, and falls
back to sliding-window chunking with the label made explicit for those
8 filings rather than guessing.

Result across all 15: `AAPL` 228 chunks, `MSFT` 374 (fallback), `NVDA`
384 (fallback), `JPM` 1166, `BAC` 1147 (fallback), `JNJ` 374, `PG` 329,
`CVX` 568 (fallback), `WMT` 414 (fallback), `KO` 719 (fallback), `BA`
453, `VZ` 471, `CAT` 458, `F` 780 (fallback), `PFE` 763 (fallback).

### What I'd do differently
A stronger version of this (didn't build it, flagging for later if
retrieval quality on the 8 fallback filings turns out to matter for the
RAGAS numbers in Phase 8): use the filing's own table of contents as
ground truth for section titles first, then search the body for each
title string specifically as an anchor, instead of relying purely on
the "Item X." numbering pattern. Didn't build this now because it's
meaningfully more code for a benefit that's currently theoretical - the
honest fallback is a legitimate engineering answer, not a placeholder,
and RAGAS numbers (Phase 8) are the real signal for whether the
fallback filings' retrieval quality is actually a problem worth solving
versus good enough as-is.

---

## 2026-08-14 — Phase 3: Filings Agent (retrieval + generation + grounding)

### What I built
`agents/filings_agent.py`: `retrieve()` (Chroma query filtered by ticker,
reusing Phase 2's index), `generate_answer()` (Ollama chat call with a
context block of labeled retrieved chunks), and two independent
verification layers - `check_citations_exist()` (structural: does every
`(Item X)` citation in the answer correspond to a section that was
actually retrieved?) and `check_semantic_grounding()` (content: does
every sentence in the answer have a retrieved chunk it's actually close
to, by embedding cosine similarity?) - combined in `answer_query()`.
`agents/test_filings_agent.py`: 8 tests, mixing fast deterministic unit
tests of the grounding-check logic against fabricated inputs (no LLM
call needed to test that logic) with slower real end-to-end calls.

### Why this approach
Two independent grounding signals, not one, because they catch different
failure modes: citation-checking catches a *hallucinated label*
(claiming "(Item 9)" when nothing from Item 9 was retrieved) but would
miss a *hallucinated claim attached to a real label* (correctly citing
"(Item 1A)" while saying something Item 1A's actual text doesn't
support) - semantic similarity catches that second case, which pure
citation-checking structurally cannot. Neither is a proof of
correctness on its own (semantic similarity is a heuristic, not an
entailment check), but together they're a real, explainable,
zero-additional-cost signal (reuses the same embedding model already in
the stack) that's far better than trusting the model's citations at
face value.

Two Ollama-connected agents in this project make direct LLM calls
(Filings Agent here, Synthesis Agent later) while the Market Agent goes
through MCP - this is deliberate, not inconsistent: MCP is the boundary
specifically for the Market Agent's external tool calls (Section 7 of
the doc), not a blanket rule that every agent must be wrapped in a
protocol. The Filings Agent's retrieval is over a local index with no
external consumer, so it stays a direct function call.

### Difficulty encountered (four real ones, in the order they were found)

**1. Citation format not followed at all, first attempt.** First prompt
just stated the citation rule in prose. Real test against AAPL: zero
`(Item X)` citations anywhere in the answer, despite an explicit
numbered instruction. Fixed by adding one worked example to the system
prompt (context → question → correctly-cited answer) - this fixed that
specific test case, but not universally (see difficulty 4).

**2. Sentence-splitter bug inflating false grounding failures.** The
first grounding-check run flagged markdown list markers ("2.", "3.") as
"ungrounded sentences" - they're not sentences at all, they're an
artifact of splitting on `[.!?]` without accounting for numbered-list
formatting. Fixed by filtering split results to require at least 3
letters, so numeric fragments never enter the grounding check at all.

**3. Two real chunking bugs, found only because an actual generated
answer looked wrong.** Testing against NVDA (a `sliding_window_fallback`
filing), a retrieved chunk started `"cally with the SEC..."` - visibly
a word cut in half. Two separate causes, found by actually reading the
retrieved chunks instead of only reading the LLM's answer:
  - `_split_on_paragraphs`'s hard-split fallback (for a single paragraph
    longer than `MAX_CHUNK_CHARS`) sliced on raw character indices.
    Fixed with a word-boundary-respecting split instead.
  - Separately, the *overlap* logic (`pieces[i-1][-overlap_chars:]`)
    did the exact same raw-character-slice mistake when building the
    prefix carried into the next chunk - fixing the hard-split alone
    didn't fully fix the symptom, because this second slice was an
    independent source of the same bug. Fixed by dropping any partial
    leading word-fragment from the slice.
  - A **bigger, related finding** while investigating this: an initial
    "how many chunks look suspicious" check flagged 304/381 (80%) of
    NVDA's chunks - which led to discovering that `BeautifulSoup.get_text()`
    has no CSS engine, so it was extracting text from `display:none`
    elements, specifically the `<ix:header>` block that holds NVDA's
    entire hidden inline-XBRL tagging layer (raw fact identifiers like
    `us-gaap:CommonStockMember`, context IDs, no prose at all). On
    closer, more precise measurement, the *actual* contamination was
    17/381 chunks (~4.5%) - the 80% figure was a false alarm from an
    imprecise first heuristic (flagging any lowercase chunk-start, which
    mostly just caught normal mid-sentence sliding-window starts, not
    real junk). Both numbers are worth keeping in the record: the
    over-broad first check would have been a bad exaggeration to report
    as fact, and re-measuring more precisely before concluding "how big
    is this problem" is the actual lesson, not just "fixed a bug." Fixed
    by stripping `<ix:header>` and any `display:none` element before
    calling `get_text()`. Rebuilt the full index after each of these
    three fixes and re-ran the full test suite each time rather than
    batching the fixes - each rebuild takes ~2-3 minutes, cheap insurance
    against a fix silently not doing what I thought.

**4. Citation-format compliance is inconsistent, not just "off" -
confirmed non-deterministic across queries with the light model.**
After the one-shot-example fix (difficulty 1) worked on the AAPL supply
chain question, it did *not* reliably reproduce: a JPM credit-risk
question came back with zero citations despite clearly using retrieved
content; a deliberately unanswerable question ("what will the stock
price be in 2030") sometimes correctly triggered the "insufficient
information" refusal and sometimes instead hallucinated an unrelated
answer about term debt figures pulled from a retrieved financial-
statements chunk. This also exposed a real gap in
`check_citations_exist`: an answer with **zero** citations trivially has
**zero hallucinated** citations too, so it was passing
`all_citations_valid: True` - vacuously, not because it was actually
grounded. Fixed by adding an explicit `missing_required_citation` check
(zero citations + not a refusal = flagged), covered by a dedicated unit
test (`test_check_citations_flags_missing_citation_on_factual_claim`)
using a fabricated example specifically because this exact bug would
otherwise be invisible to a test that only checks the "citations valid"
field superficially.

### How it was resolved
Ran the identical JPM credit-risk question against
`qwen2.5:7b-instruct-q4_0` instead of the default `1.5b` light model:
correctly cited `(Item 15)` (the real retrieved section), latency
48.6s vs. roughly 15-25s for the light model on comparable queries -
consistent with the project doc's known constraint that a 7B q4 model
partially spills to CPU/RAM on this 4GB GPU. Deliberately did **not**
switch the default model based on this single comparison - a handful of
spot checks isn't a real answer to "does model size actually matter
here," and the project already has the right tool for that question:
Phase 8's RAGAS faithfulness/citation-accuracy numbers, run at scale,
comparing both models properly instead of trusting my own read of 2-3
examples. `MODEL_NAME` stays configurable via the `LIGHT_MODEL` env var
(defaults to `1.5b` for fast local dev), with the model-choice decision
explicitly deferred to real evaluation data rather than decided here on
vibes.

### What I'd do differently
Would inspect retrieved chunk *text*, not just the LLM's final answer,
from the very first test - three of the four difficulties above
(sentence-splitter, both chunking bugs, part of the citation
inconsistency) were only found by actually reading what got retrieved,
not by reading what the model produced from it. A wrong-looking answer
is a symptom; the retrieved context is where the actual cause usually
is, and checking it first would have been faster than reasoning
backward from generation output each time.

### Follow-up: the yfinance rate-limiting flag from Phase 1 just triggered
Running the full test suite during this phase, `test_fetch_price_history_valid_tickers`
failed on a live run with `$AAPL: possibly delisted; no price data found` -
obviously false (Apple is not delisted). Retried the identical call three
times immediately after with 2s gaps: all three succeeded. This is exactly
the transient Yahoo Finance flakiness flagged as a hypothesis (not yet
observed) at the end of the Phase 1 log entry - now it's an observed fact,
not a hypothesis, and it's a real, if minor, in interview material: the
function correctly returned a structured `{"ok": False, ...}` result
rather than crashing the test run, which is the exact resilience the
Phase 1 envelope-return design was for. No code change needed here - this
is a live external dependency being flaky, not a bug - but worth watching
if it recurs at higher frequency once the graph is making repeated calls
per research query (Phase 5+).

---

## 2026-08-14 — Phase 4: Synthesis Agent (cross-source reasoning)

### What I built
`agents/synthesis_agent.py::synthesize_report(ticker, market, filings)` -
takes a Market Agent-shaped bundle (`fundamentals` + `indicators`
results) and a list of Filings Agent Q&A results (asked
`FILINGS_QUESTIONS`, two fixed questions: main risk factors, and
management's discussion of recent performance), and produces a 5-section
markdown report (Company Overview, Market Snapshot, Key Risks from
Filings, Market vs. Filings: Agreement or Tension, Data Gaps) using the
7B model. Either input can be `None` (agent was skipped/failed
upstream); both `None` returns a structured error without an LLM call
at all - directly implementing the project doc's Section 1 routing rule
("if both fail, return a clear structured error, not a hallucinated
report") a full phase before the graph that will actually enforce that
routing exists.

`check_cross_source_reasoning()`: an automatable proxy for "did this
actually reason across sources, or just paste them" - checks the
Agreement/Tension section specifically for non-trivial length, at least
one connective/comparative word (however, despite, tension, ...), and
mentions of terms from *both* sources in that section. Built per the
project doc's explicit instruction to "test for this specifically."

Tested per the doc's Build Order step 5: mocked Market/Filings inputs
first (`agents/test_synthesis_agent.py`), including a deliberately
crafted tension scenario (mock company: strong recent stock performance
+ filings disclosing 40% customer concentration risk with contract
renewal uncertain) - then a real end-to-end chain test (actual
`fetch_fundamentals`/`compute_indicators` + actual `answer_query` calls
+ synthesis) against Ford. 7/7 tests pass, ~2.5 minutes total (most of
that is real 7B model calls, not test overhead).

### Why this approach
Two fixed filings questions, not an open-ended "summarize everything" -
the Synthesis Agent needs *comparable, structured* filings input to
reason against market data, and an unconstrained "tell me about this
company's filing" call would produce inconsistent shape run to run. Risk
factors + MD&A performance discussion were chosen because they're the
two sections most likely to actually connect to market data (a risk
factor can be checked against price/volatility; MD&A performance
commentary can be checked against recent % change) - Item 1 (Business)
or Item 2 (Properties), for contrast, have much less to say that market
data could meaningfully agree or disagree with.

7B model, not the Filings Agent's default 1.5B - this is the one node
the project doc explicitly earmarks for the most reasoning-heavy step
(Section 2), and cross-source reasoning is a harder task than
single-source retrieval+citation. Worth the latency cost here
specifically (~75-100s per report locally) in a way it wasn't
obviously worth it for the Filings Agent, where the decision was
deferred to Phase 8's numbers instead of decided outright.

The heuristic reasoning-check exists for the same reason the Filings
Agent has two grounding checks instead of trusting the model: an
automatable, zero-marginal-cost signal on *every* run, not a substitute
for real evaluation. Phase 8's manual rubric-scored review across ~10
companies is still the real answer to "is the synthesis actually good"
- this just catches the obvious failure (empty/one-line tension
section, or a section that only talks about one source) cheaply and
immediately, the same relationship the Filings Agent's grounding checks
have to Phase 8's RAGAS numbers.

### Difficulty encountered
Genuinely, less than expected - the 7B model produced real cross-source
reasoning on the *first* attempt against the mock tension scenario,
with no prompt iteration needed (see the actual output in this session:
"the market does not seem to be fully pricing in these risks, as
evidenced by the positive stock movement despite the disclosed
dependency" - that's a real connection, not two paragraphs stapled
together). This is worth recording precisely because the project doc
anticipated pasting-not-reasoning as a likely, expected failure mode
("this is a very common, very defensible difficulty to have hit") -
and here it wasn't, on this model, for this scenario. Not claiming this
generalizes perfectly across all 15 companies without checking (that's
exactly what Phase 8's manual review across ~10 companies is for) - but
honest logging cuts both ways: a difficulty that didn't materialize is
as worth recording accurately as one that did, rather than searching
for a struggle to report just because one was expected.

**A different, real, unflagged problem did show up** in the real
end-to-end Ford test: the model's own generated commentary contained a
factual/logical error unrelated to grounding - it described "adjusted
EBIT margin also saw an improvement from 5.9% to 5.5%" when 5.9% to
5.5% is a *decline*, not an improvement. This is a meaningfully
different failure mode from anything the Filings Agent's grounding
checks catch: the underlying numbers here were plausibly grounded
(pulled from real retrieved figures), but the model's own interpretive
language about a correctly-retrieved number was simply wrong. Citation-
existence checking and semantic-similarity grounding both operate on
"is this claim traceable to a source chunk" - neither is designed to
catch "is this arithmetic/directional claim about two correctly-sourced
numbers actually correct." That's a distinct problem (numerical/logical
reasoning correctness) from the RAG-specific one (faithfulness to
retrieved text) this project's grounding checks were built for.

### How it was resolved
Not fixed - logged as a known limitation rather than patched with a
narrow rule, because a narrow fix (e.g. regex-checking for "improvement"
near a negative percentage delta) would be exactly the kind of brittle,
overfit patch that doesn't generalize past the one example that
motivated it. This is real scope for a proper fix (a numerical-
consistency check comparing stated directional language against the
actual sign of referenced deltas) but building that well requires
seeing more examples of how it fails, which is what Phase 8's broader
evaluation across more companies and questions is for.

### What I'd do differently
Nothing about the Synthesis Agent's design - the mock-first testing
approach worked exactly as the project doc intended (caught the target
failure mode's absence with a real, deliberately adversarial scenario
before ever touching a live agent chain). The EBIT-margin finding is a
reminder to keep watching *specific numbers* in generated reports during
Phase 8's manual review, not just whether sections are well-connected
prose - "reads well and cites sources" and "is arithmetically correct"
are different bars, and this project's grounding infrastructure only
verifies the first one.

---

## 2026-08-14 — Phase 2: Embedding + Chroma index, retrieval sanity test

### What I built
`ingestion/build_index.py`: chunks every downloaded filing
(`ingestion/chunker.py`), embeds each chunk with
`sentence-transformers/all-MiniLM-L6-v2`, and writes them into a single
persistent Chroma collection at `data/index/` with per-chunk metadata
(`ticker`, `section_item`, `section_title`, `chunk_index`, `method`).
One collection for all 15 companies, filtered by `ticker` at query time
— this is the concrete payoff of the Phase 0 Chroma-over-FAISS decision
finally being exercised. Ran it end to end: **8,628 chunks indexed
across 15/15 companies** (228 for AAPL up to 1,166 for JPM, reflecting
real filing-length differences — banks' 10-Ks run enormous due to
detailed financial-statement notes).

`ingestion/test_retrieval.py`: standalone sanity tests (no labeled
answer set yet — that's RAGAS, Phase 8) confirming: the index is
queryable, `where={"ticker": ...}` filtering actually restricts results
to one company, a section-aware filing's top result for a risk-factors
query carries the correct `Item 1A` label, a fallback filing's top
results are honestly labeled `section_item: "unknown"` rather than a
guessed section, and an unfiltered cross-company query
("electric vehicle production and battery supply") surfaces Ford — the
one auto/EV company in the universe — near the top, which is a small
but real signal that the embeddings are semantically meaningful, not
just structurally correct.

### Why this approach
Chunk size ties directly back to the embedding model choice from Phase
0 (`all-MiniLM-L6-v2`, chosen for running fine on CPU with no GPU
needed) — `chunker.py`'s `MAX_CHUNK_CHARS = 1200` exists specifically
because that's roughly this model's effective 256-token window; this
is one config decision spanning two files/phases and worth remembering
as connected if either changes later. Each `build_index()` run deletes
and recreates the collection first, rather than appending — makes the
index reproducible from `data/filings/` + the current chunker code
every time, instead of silently accumulating duplicate/stale chunks
across repeated runs during development.

### Difficulty encountered
None at this step — the harder problems (data source, chunking) were
already worked through in the two previous entries. Batching
`collection.add()` calls at 200 chunks was a precaution taken before
running against the largest filings (JPM/BAC, 1000+ chunks) rather than
a fix for an observed failure; worth noting since it's a "did this
proactively" entry, not a "this broke" entry, and the doc asks for
honesty in both directions.

### How it was resolved
N/A — ran cleanly on the first attempt after the chunker itself was
validated.

### What I'd do differently
Nothing at this scale yet. Flag for Phase 8: the RAGAS test set should
deliberately include questions against both section-aware and fallback
filings, so the faithfulness/context-precision numbers can be compared
across the two chunking methods — that comparison is the real evidence
for whether the fallback's honesty-over-guessing tradeoff cost
meaningful retrieval quality, versus just being a reasonable
engineering compromise that didn't matter in practice. Currently a
hypothesis, not a measured fact.

---
