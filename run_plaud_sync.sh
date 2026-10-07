#!/bin/bash
# launchd: com.bear.voice-plaud-sync — fired daily at 08:30 and 20:30.
# Plaud cloud -> capture/ (solo dictation, for pipeline A) or 23_Meetings/ (conversations).
# Headless + idempotent (.plaud_sync_ledger.json dedups). Manual: bash run_plaud_sync.sh

PROJECT_DIR="/Users/bearliu/Desktop/ClaudeCode/voice-daily-note"
PYTHON="/usr/bin/python3"
# plaud is a node script under nvm; launchd's PATH has neither. Newest installed node wins.
NODE_BIN="$(ls -d "$HOME"/.nvm/versions/node/*/bin 2>/dev/null | sort -V | tail -1)"
export PATH="$NODE_BIN:/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin"
# Logs live outside the Desktop tree — see run_bookshelf_sync.sh for why.
LOG_DIR="/Users/bearliu/Library/Logs/voice-daily-note"
LOG="$LOG_DIR/plaud_sync.log"
mkdir -p "$LOG_DIR"

cd "$PROJECT_DIR" || exit 1

{
  echo "===== plaud_sync: $(date '+%Y-%m-%d %H:%M:%S %Z') ====="
  "$PYTHON" plaud_sync.py
  rc=$?
  echo "===== Exit code: $rc ====="
  echo
} >> "$LOG" 2>&1

if [ "$rc" -eq 2 ]; then
  osascript -e "display notification \"Plaud 登录过期，终端跑 plaud login 后再手动同步\" with title \"Plaud 同步 · 需要重新登录\" sound name \"Basso\""
elif [ "$rc" -ne 0 ]; then
  osascript -e "display notification \"Plaud 同步失败 (exit $rc)，看 ~/Library/Logs/voice-daily-note/plaud_sync.log\" with title \"Plaud 同步 · 失败\" sound name \"Basso\""
fi
exit $rc
