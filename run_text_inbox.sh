#!/bin/bash
# launchd: com.bear.voice-text-inbox — fired daily at 09:30.
# Pipeline C: iCloud _inbox/text/*.md -> Claude metadata -> Obsidian Daily Notes.
# Headless + idempotent (.text_inbox_ledger.json dedups). No-ops when inbox empty.

PROJECT_DIR="/Users/bearliu/Desktop/ClaudeCode/voice-daily-note"
PYTHON="/usr/bin/python3"
# Logs live outside the Desktop tree — see run_bookshelf_sync.sh for why.
LOG_DIR="/Users/bearliu/Library/Logs/voice-daily-note"
LOG="$LOG_DIR/text_inbox.log"
mkdir -p "$LOG_DIR"

cd "$PROJECT_DIR" || exit 1

{
  echo "===== text_inbox: $(date '+%Y-%m-%d %H:%M:%S %Z') ====="
  "$PYTHON" text_inbox.py
  rc=$?
  echo "===== Exit code: $rc ====="
  echo
} >> "$LOG" 2>&1

# Surface silent failure: launchd swallows it otherwise.
if [ "$rc" -ne 0 ]; then
  osascript -e "display notification \"text inbox 失败 (exit $rc)，看 ~/Library/Logs/voice-daily-note/text_inbox.log\" with title \"Voice Daily Note · 失败\" sound name \"Basso\""
fi
exit $rc
