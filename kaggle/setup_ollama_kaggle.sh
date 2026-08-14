#!/bin/bash
# Run this as a shell cell at the top of a Kaggle notebook (Settings -> Accelerator: GPU T4x2 or P100,
# Settings -> Internet: On) before any eval/latency script. Installs and starts Ollama, pulls the
# same models used locally so numbers are comparable, and leaves the server running in the background
# for the rest of the notebook session.

set -e

curl -fsSL https://ollama.com/install.sh | sh

# Start the server in the background and give it a moment to come up
nohup ollama serve > /kaggle/working/ollama.log 2>&1 &
sleep 5

# Same models used in local dev, so RAGAS/latency numbers are comparable across environments
ollama pull qwen2.5:7b-instruct-q4_0
ollama pull qwen2.5:1.5b-instruct-q4_0

echo "Ollama ready. Set OLLAMA_HOST=http://localhost:11434 (default) before running eval scripts."
