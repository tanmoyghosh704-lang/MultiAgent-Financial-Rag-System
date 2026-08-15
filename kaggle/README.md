# Kaggle usage: what runs where

Local laptop (RTX 1650, 4GB VRAM) is used for **development and small
smoke tests only**. Anything batch-sized or LLM-heavy runs on Kaggle
instead, so the laptop stays responsive and the run finishes faster on a
free T4/P100 GPU.

| Job | Where | Why |
|---|---|---|
| Writing/debugging agent, graph, chunking, MCP code | Local | Fast iteration loop, no need for scale |
| Smoke tests (1-2 companies, `qwen2.5:1.5b`) | Local | Cheap, quick feedback |
| Building the vector index for all 15 companies | Local (CPU) | `sentence-transformers` embedding is CPU-fine per plan; only moved to Kaggle if it proves too slow in practice — log it if so |
| Full RAGAS eval (30-40 questions x 4 metrics, each metric = multiple LLM judge calls with `qwen2.5:7b`) | **Kaggle** | LLM-call-heavy, GPU makes qwen2.5:7b fast instead of partially spilling to CPU/RAM like it does locally |
| Latency benchmark (sequential vs parallel graph runs, MCP overhead) | **Kaggle** | Needs many repeated 7B-model agent calls for stable timing numbers |
| Batch synthesis generation for the ~10-company manual review | **Kaggle** | Same reason — 7B model, many calls |

## How to run a heavy job on Kaggle

1. Create a new Kaggle notebook. Settings -> Accelerator: GPU (T4 x2 or
   P100). Settings -> Internet: On (needed to install Ollama and pull
   models).
2. Upload/clone this repo into the notebook (Kaggle "Add Data" with a
   GitHub repo, or push this project to a private GitHub repo and clone
   it in a cell).
3. Run `bash kaggle/setup_ollama_kaggle.sh` in a shell cell — installs
   Ollama, starts the server, pulls the **same models used locally**
   (`qwen2.5:7b-instruct-q4_0`, `qwen2.5:1.5b-instruct-q4_0`) so numbers
   are comparable across environments, not just "faster because
   different model."
4. `pip install -r requirements.txt` in a notebook cell.
5. Run the eval/latency script exactly as written locally, e.g.
   `python eval/ragas_eval.py`. No code changes needed — every script
   reads `OLLAMA_HOST` (defaults to `http://localhost:11434`, which is
   correct both locally and inside the Kaggle notebook since Ollama runs
   in-notebook, not remotely) and model names from `.env`/environment
   variables, never hardcoded. This portability is deliberate — see the
   project doc's Phase 6/8 notes.
6. Download result artifacts (`results/*.json`, plots) from
   `/kaggle/working/` before the session ends — Kaggle sessions are
   ephemeral, nothing persists automatically.

## Running the full RAGAS eval on Kaggle (Phase 8)

Validated locally on a 2-question subset first (`python -m eval.ragas_eval
--limit 2`) to confirm the pipeline itself is correct before spending
real time on it - see `LOG.md` Phase 8 entry. That run took **8m14s for
2 questions**, which extrapolates to roughly 2 hours for the full
30-question set locally - exactly the kind of job this project's
local/Kaggle split exists for, so the full run belongs here, not on the
laptop.

Steps, in addition to the general setup above:

1. `data/filings/` and `data/index/` are both gitignored (regenerable,
   and `data/index/` in particular is a multi-hundred-MB Chroma DB not
   worth committing) - a fresh clone on Kaggle won't have them. Rebuild
   both before running the eval:
   ```bash
   python -m ingestion.download_filings
   python -m ingestion.build_index
   ```
   (a minute or two each - SEC downloads and CPU embedding, not
   GPU-bound, so this part isn't meaningfully faster on Kaggle, it's
   just necessary setup).
2. Run the full eval:
   ```bash
   python -m eval.ragas_eval
   ```
   Uses `qwen2.5:7b-instruct-q4_0` as the judge LLM (`JUDGE_MODEL` in
   `eval/ragas_eval.py`) and the same `all-MiniLM-L6-v2` embeddings used
   throughout this project - no OpenAI key needed.
3. `eval/ragas_eval.py` already sets `RunConfig(timeout=900,
   max_workers=2)` rather than RAGAS's defaults
   (`timeout=180, max_workers=16`) - the defaults assume a high-throughput
   remote API where 16 concurrent judge calls genuinely run in parallel;
   against a single local Ollama instance they just queue behind each
   other and blow the timeout (this is exactly what happened on the
   first local validation attempt - see LOG.md). On Kaggle's GPU this
   config is probably still conservative (real headroom exists to raise
   `max_workers` there, since GPU-resident inference is fast enough that
   more concurrent jobs may actually help) - worth tuning up if the
   Kaggle run is slow, rather than assuming the local-hardware-tuned
   values are automatically right there too.
4. Results land in `data/eval/ragas_report.json` - unlike `data/filings/`
   and `data/index/`, `data/eval/` is NOT gitignored (it's small,
   human-readable, and worth keeping as a record of what the numbers
   were on a given run).
5. Run `python kaggle/collect_results.py` as the last cell - copies the
   eval report(s) into `/kaggle/working/`, which is what Kaggle
   automatically packages as the notebook's downloadable Output once you
   hit **Save Version**. This is the reliable way to get a file out of a
   Kaggle notebook - a JS-triggered auto-download is unreliable during a
   headless Save Version run since there's no browser tab guaranteed to
   be watching; anything under `/kaggle/working/` at the end of the run
   just appears on the Output tab regardless.
6. After Save Version finishes, download the report(s) from the
   notebook's Output tab and commit them into `data/eval/` alongside the
   `LOG.md`/`results/writeup.md` summary of the same numbers.

## Known gotcha: ragas import

`ragas` currently has an open upstream bug where a bare `import ragas`
crashes on any modern `langchain-community` (unrelated to Kaggle vs
local — see `LOG.md` Phase 0 entry and `eval/_ragas_compat.py`). Any
script that imports `ragas` (i.e. `eval/ragas_eval.py`, built in Phase 8)
must call `install_ragas_vertexai_stub()` from that module first — this
applies identically on Kaggle since it's a pure-Python fix, not an
environment-specific one.

## Honest tradeoff

This adds a manual step (re-running setup on every fresh Kaggle
session — no persistent server) and the two environments can drift if
package versions differ. It's still worth it here because a 7B q4 model
partially spills to CPU/RAM on the 4GB local GPU (confirmed slow in the
routing project), while Kaggle's free GPU runs it fully in VRAM.
