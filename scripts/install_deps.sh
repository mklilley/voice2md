#!/usr/bin/env bash
set -euo pipefail

echo "Installing optional system dependencies for voice2md."
echo

if ! command -v brew >/dev/null 2>&1; then
  echo "Homebrew not found. Install Homebrew first, then rerun this script."
  exit 1
fi

brew install whisper-cpp ffmpeg

echo
echo "Next:"
echo "1) Download a whisper.cpp ggml model file (e.g. ggml-medium.bin) and set it in config.yaml"
echo "2) Install the Python package in editable mode:"
echo "   python3 -m venv .venv && source .venv/bin/activate && pip install -e ."

