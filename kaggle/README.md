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
