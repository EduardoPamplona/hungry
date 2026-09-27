#!/usr/bin/env bash
# Download the local LLM (Qwen2.5-3B-Instruct, Q4_K_M GGUF) into ./models,
# named to match LLM_MODEL_FILE in compose. ~2 GB. Re-runnable (skips if present).
set -euo pipefail

DIR="$(cd "$(dirname "$0")/.." && pwd)/models"
OUT="$DIR/qwen2.5-3b-instruct-q4_k_m.gguf"
URL="https://huggingface.co/bartowski/Qwen2.5-3B-Instruct-GGUF/resolve/main/Qwen2.5-3B-Instruct-Q4_K_M.gguf"

mkdir -p "$DIR"
if [ -f "$OUT" ]; then
  echo "Model already present: $OUT"
  exit 0
fi

echo "Downloading Qwen2.5-3B-Instruct Q4_K_M -> $OUT"
curl -fL --progress-bar -o "$OUT" "$URL"
echo "Done: $(du -h "$OUT" | cut -f1)"
