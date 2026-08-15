"""Diagnostic for the answer_relevancy == NaN issue (see LOG.md Phase 8
follow-up entries). Ruled out two hypotheses via isolated local testing,
both passing cleanly there: concurrency (still NaN with max_workers=1,
fully serial) and response length/complexity (a realistic long
multi-point response still generated valid synthetic questions locally).
Since the same isolated mechanism has not reproduced the failure
locally but fails 100% of the time on Kaggle across two full runs, the
next most likely explanation is something environment-specific to
Kaggle - this script surfaces the real exception RAGAS's default
`raise_exceptions=False` currently swallows into a silent NaN, and
prints the exact package versions in play so a version mismatch between
local dev and Kaggle can be checked directly instead of guessed at.

Usage on Kaggle: `!python -m kaggle.diagnose_answer_relevancy` (after the
usual Ollama setup - see kaggle/README.md). Must use `-m` module
invocation, not a bare script path - the same class of bug already hit
once in Phase 7 (mcp_server/market_data_server.py): running as a plain
script only puts this file's own directory on sys.path, not the repo
root, so the sibling `eval` package isn't importable. `-m` from the
repo root fixes it the same way it did there.
"""

from __future__ import annotations

import asyncio

from eval._ragas_compat import install_ragas_vertexai_stub

install_ragas_vertexai_stub()

import langchain_ollama  # noqa: E402
import pydantic  # noqa: E402
import ragas  # noqa: E402
from langchain_ollama import ChatOllama  # noqa: E402
from ragas.llms import LangchainLLMWrapper  # noqa: E402
from ragas.metrics._answer_relevance import ResponseRelevanceInput, ResponseRelevancePrompt  # noqa: E402

LONG_RESPONSE = """The main risk factors disclosed in the filing are:

1. Failure to meet the evolving needs of the industry and markets, which could adversely impact financial results.
2. Competition, which could reduce market share and financial results.
3. Long manufacturing lead times and uncertain supply and capacity availability, which could lead to mismatches between supply and demand.
4. Scrutiny of corporate sustainability practices could result in financial, reputational, or operational harm and liability.
5. Issues relating to the responsible use of technologies, including AI, may result in reputational or financial harm and liability."""


async def main() -> None:
    print(f"ragas version: {ragas.__version__}")
    print(f"langchain_ollama version: {langchain_ollama.__version__}")
    print(f"pydantic version: {pydantic.__version__}")
    print()

    judge_llm = LangchainLLMWrapper(ChatOllama(model="qwen2.5:7b-instruct-q4_0"))
    prompt = ResponseRelevancePrompt()

    for label, response_text in [("short", "The company faces risks such as litigation and government investigations."), ("long/multi-point", LONG_RESPONSE)]:
        print(f"--- Testing with {label} response ---")
        prompt_input = ResponseRelevanceInput(response=response_text)
        try:
            result = await prompt.generate_multiple(data=prompt_input, llm=judge_llm, n=3)
            for r in result:
                print(f"  question: {r.question!r} | noncommittal: {r.noncommittal}")
        except Exception as e:
            print(f"  EXCEPTION: {type(e).__name__}: {e}")
            import traceback

            traceback.print_exc()
        print()


if __name__ == "__main__":
    asyncio.run(main())
