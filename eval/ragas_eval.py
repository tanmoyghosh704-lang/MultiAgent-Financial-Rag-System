"""RAGAS evaluation of the Filings Agent (project doc Phase 8A):
faithfulness, answer relevancy, context precision, context recall over
the 30-question test set in data/eval/ragas_test_set.json.

Portable local/Kaggle by construction (see kaggle/README.md) - the judge
LLM is Ollama (via SYNTHESIS_MODEL, same 7B model used for the Synthesis
Agent's reasoning-heavy work) and embeddings are the same
sentence-transformers/all-MiniLM-L6-v2 model used everywhere else in this
project's RAG pipeline, not a paid API. No OpenAI key, no Google Vertex,
nothing that requires anything beyond what's already running locally or
on a Kaggle notebook.

Every question in the test set makes one real Filings Agent call (Ollama
generation) PLUS each of the 4 RAGAS metrics makes its own judge-LLM
call(s) per question - this is the actual reason this eval is scoped to
run on Kaggle for the full 30-question set rather than tie up a laptop
for hours; see LOG.md for the local small-subset validation run that
proves this pipeline is correct before handing the full run off.

Must call install_ragas_vertexai_stub() before any ragas import - see
eval/_ragas_compat.py for why (open upstream ragas bug, unrelated to
this project).
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from eval._ragas_compat import install_ragas_vertexai_stub

install_ragas_vertexai_stub()

from agents.filings_agent import answer_query  # noqa: E402
from langchain_community.embeddings import HuggingFaceEmbeddings  # noqa: E402
from langchain_ollama import ChatOllama  # noqa: E402
from ragas import EvaluationDataset, evaluate  # noqa: E402
from ragas.embeddings import LangchainEmbeddingsWrapper  # noqa: E402
from ragas.llms import LangchainLLMWrapper  # noqa: E402
from ragas.metrics import AnswerRelevancy, ContextPrecision, ContextRecall, Faithfulness  # noqa: E402
from ragas.run_config import RunConfig  # noqa: E402

# RAGAS defaults (timeout=180s, max_workers=16) assume a high-throughput
# remote API where 16 concurrent judge calls actually run in parallel.
# Locally, there's one Ollama instance serving one model - 16 concurrent
# jobs just queue behind each other, and since a single 7B-model call on
# this hardware already takes 70-130s (see Phase 4/5 LOG.md entries), job
# #16 could wait 15+ calls deep before even starting, blowing the 180s
# timeout before it ever gets a turn. First real run hit exactly this:
# all 8 jobs (2 questions x 4 metrics) TimeoutError'd, all scores NaN.
# max_workers=2 keeps some overlap without starving any job for 25+
# minutes; timeout=900 gives real headroom for this hardware's actual
# per-call latency instead of assuming API-speed responses.
LOCAL_OLLAMA_RUN_CONFIG = RunConfig(timeout=900, max_workers=2)

TEST_SET_PATH = Path(__file__).resolve().parent.parent / "data" / "eval" / "ragas_test_set.json"
REPORT_PATH = Path(__file__).resolve().parent.parent / "data" / "eval" / "ragas_report.json"

JUDGE_MODEL = "qwen2.5:7b-instruct-q4_0"
EMBEDDING_MODEL = "all-MiniLM-L6-v2"


def build_evaluation_dataset(questions: list[dict[str, Any]]) -> tuple[EvaluationDataset, list[dict[str, Any]]]:
    """Generates a real Filings Agent answer for each test question and
    packages it into RAGAS's expected schema (user_input/response/
    retrieved_contexts/reference - confirmed via introspection against
    the installed ragas version, not assumed). Questions where retrieval
    itself failed are skipped, not fabricated an answer for - that would
    poison the eval with a non-answer scored as if it were a real one."""
    records = []
    skipped = []
    for q in questions:
        result = answer_query(q["ticker"], q["question"])
        if not result["ok"]:
            skipped.append({"id": q["id"], "reason": result.get("error", "unknown")})
            continue
        records.append(
            {
                "user_input": q["question"],
                "response": result["answer"],
                "retrieved_contexts": [c["text"] for c in result["retrieved_chunks"]],
                "reference": q["ground_truth"],
                "_id": q["id"],
                "_ticker": q["ticker"],
            }
        )
    return EvaluationDataset.from_list(records), skipped


def run_ragas_eval(limit: int | None = None) -> dict[str, Any]:
    with open(TEST_SET_PATH, encoding="utf-8") as f:
        test_set = json.load(f)

    questions = test_set["questions"][:limit] if limit else test_set["questions"]
    dataset, skipped = build_evaluation_dataset(questions)

    judge_llm = LangchainLLMWrapper(ChatOllama(model=JUDGE_MODEL))
    judge_embeddings = LangchainEmbeddingsWrapper(HuggingFaceEmbeddings(model_name=EMBEDDING_MODEL))

    result = evaluate(
        dataset,
        metrics=[Faithfulness(), AnswerRelevancy(), ContextPrecision(), ContextRecall()],
        llm=judge_llm,
        embeddings=judge_embeddings,
        run_config=LOCAL_OLLAMA_RUN_CONFIG,
    )

    scores_df = result.to_pandas()
    per_question = scores_df.to_dict(orient="records")

    summary = {
        "num_questions_evaluated": len(dataset),
        "num_questions_skipped": len(skipped),
        "skipped": skipped,
        "mean_scores": {
            metric: round(float(scores_df[metric].mean()), 4)
            for metric in ["faithfulness", "answer_relevancy", "context_precision", "context_recall"]
            if metric in scores_df.columns
        },
        "per_question": per_question,
    }
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=None, help="Only run the first N questions (for local validation)")
    args = parser.parse_args()

    summary = run_ragas_eval(limit=args.limit)

    print(f"Evaluated {summary['num_questions_evaluated']} questions "
          f"({summary['num_questions_skipped']} skipped: {summary['skipped']})")
    print("\nMean scores:")
    for metric, score in summary["mean_scores"].items():
        print(f"  {metric}: {score}")

    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps(summary, indent=2, default=str), encoding="utf-8")
    print(f"\nFull report written to {REPORT_PATH}")
