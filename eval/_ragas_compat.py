"""Workaround for a known, open ragas bug (as of 2026-08, ragas 0.4.3 and
0.3.9 both affected — see github.com/vibrantlabsai/ragas issues #2741,
#2745, #2753).

`ragas/llms/base.py` unconditionally does
`from langchain_community.chat_models.vertexai import ChatVertexAI` at
import time. `langchain-community` removed that submodule in its
provider-integration "sunset" refactor (ChatVertexAI moved to the
standalone `langchain-google-vertexai` package), so plain `import ragas`
crashes for every user who isn't touching Vertex AI — including this
project, which only ever talks to Ollama.

Installing `langchain-google-vertexai` does NOT fix this: that package
exposes `langchain_google_vertexai.ChatVertexAI`, a different import
path, while ragas's broken line imports the now-deleted
`langchain_community.chat_models.vertexai` path specifically.

Fix: insert a stub module at that exact dotted path into `sys.modules`
before ragas is imported, so Python's import machinery finds something
there and moves on. The stub's `ChatVertexAI` is never instantiated —
this project never uses Vertex AI — it only needs to exist so the import
statement doesn't raise.

Call `install_ragas_vertexai_stub()` before any `import ragas` /
`from ragas import ...` in this project.
"""

import sys
import types


def install_ragas_vertexai_stub() -> None:
    module_path = "langchain_community.chat_models.vertexai"
    if module_path in sys.modules:
        return

    try:
        __import__(module_path)
        return  # a real vertexai module exists in this environment - nothing to stub
    except ModuleNotFoundError:
        pass

    stub = types.ModuleType(module_path)

    class ChatVertexAI:  # pragma: no cover - unused stub, exists only to satisfy ragas's import
        def __init__(self, *args, **kwargs):
            raise RuntimeError(
                "ChatVertexAI is a compat stub (see eval/_ragas_compat.py) — "
                "this project does not support Vertex AI, only Ollama."
            )

    stub.ChatVertexAI = ChatVertexAI
    sys.modules[module_path] = stub
