#!/bin/bash
# Run this as a shell cell at the top of a Kaggle notebook (Settings -> Accelerator: GPU T4x2 or P100,
# Settings -> Internet: On) before any eval/latency script. Installs and starts Ollama, pulls the
# same models used locally so numbers are comparable, and leaves the server running in the background
# for the rest of the notebook session.

set -e

curl -fsSL https://ollama.com/install.sh | sh

# Start the server in the background and wait until it actually responds,
# rather than a fixed sleep - a blind `sleep 5` was found (on Kaggle,
# during Phase 8 evaluation) to sometimes not be enough time for the
# server to come up, causing every downstream ollama.chat() call to fail
# with a bare, hard-to-diagnose ConnectionError.
nohup ollama serve > /kaggle/working/ollama.log 2>&1 &
for i in $(seq 1 30); do
  if curl -sf http://localhost:11434/api/tags > /dev/null 2>&1; then
    echo "Ollama server is up (waited ${i}x2s)."
    break
  fi
  if [ "$i" -eq 30 ]; then
    echo "Ollama server did not come up after 60s - check /kaggle/working/ollama.log"
    cat /kaggle/working/ollama.log
    exit 1
  fi
  sleep 2
done

# Same models used in local dev, so RAGAS/latency numbers are comparable across environments
ollama pull qwen2.5:7b-instruct-q4_0
ollama pull qwen2.5:1.5b-instruct-q4_0

echo "Ollama ready. Set OLLAMA_HOST=http://localhost:11434 (default) before running eval scripts."
