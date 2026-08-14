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
