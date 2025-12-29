#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TEMPLATE_PATH="$ROOT_DIR/scripts/com.voice2md.plist.template"

CONFIG_DIR="$HOME/.config/voice2md"
CONFIG_PATH="$CONFIG_DIR/config.yaml"
PROMPTS_DIR="$CONFIG_DIR/prompts"
PROMPT_PATH="$PROMPTS_DIR/referee_prompt.md"
LAUNCH_AGENTS_DIR="$HOME/Library/LaunchAgents"
PLIST_PATH="$LAUNCH_AGENTS_DIR/com.voice2md.plist"

STDOUT_LOG="$HOME/Library/Logs/voice2md.launchd.log"
STDERR_LOG="$HOME/Library/Logs/voice2md.launchd.err.log"

mkdir -p "$CONFIG_DIR" "$LAUNCH_AGENTS_DIR" "$HOME/Library/Logs"

if [[ ! -f "$CONFIG_PATH" ]]; then
  cp "$ROOT_DIR/config.yaml" "$CONFIG_PATH"
  echo "Copied default config to: $CONFIG_PATH"
else
  echo "Config exists: $CONFIG_PATH"
fi

mkdir -p "$PROMPTS_DIR"
if [[ ! -f "$PROMPT_PATH" ]]; then
  cp "$ROOT_DIR/prompts/referee_prompt.md" "$PROMPT_PATH"
  echo "Copied prompt template to: $PROMPT_PATH"
else
  echo "Prompt exists: $PROMPT_PATH"
fi

sed \
  -e "s|__CONFIG_PATH__|$CONFIG_PATH|g" \
  -e "s|__WORKDIR__|$ROOT_DIR|g" \
  -e "s|__STDOUT_LOG__|$STDOUT_LOG|g" \
  -e "s|__STDERR_LOG__|$STDERR_LOG|g" \
  "$TEMPLATE_PATH" > "$PLIST_PATH"

echo "Wrote launchd plist: $PLIST_PATH"

UID_NUM="$(id -u)"
launchctl bootout "gui/$UID_NUM" "$PLIST_PATH" 2>/dev/null || true
launchctl bootstrap "gui/$UID_NUM" "$PLIST_PATH"
launchctl enable "gui/$UID_NUM/com.voice2md" || true

echo "Installed and started com.voice2md"
echo "Logs: $STDOUT_LOG (stdout), $STDERR_LOG (stderr), plus voice2md.log from config"
