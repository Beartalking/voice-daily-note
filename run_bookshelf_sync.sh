#!/bin/bash
# launchd: com.bear.voice-bookshelf-sync — fired daily at 09:40.
# Pipeline D: Daily Notes #Book/#Movie -> Books/Movies bookshelf.
# --batch skips interactive multi-match selection (headless-safe).
# KNOWN RISK: single no-match entries are auto-created; a Chinese title can collide
# with a same-named popular English work (e.g. 怒呛人生 -> The Bear). So when any
# file is auto-created, fire a notification prompting Bear to verify the new entries.

PROJECT_DIR="/Users/bearliu/Desktop/ClaudeCode/voice-daily-note"
PYTHON="/usr/bin/python3"
# Logs live outside the Desktop tree. Log files under Desktop/ClaudeCode eventually
# reach a per-file state that xpcproxy refuses as a launchd stdio target, killing the
# job with EX_CONFIG(78) before it runs and before anything is written. This job was
# silently dead from 2026-07-27 to 2026-08-03 for exactly that reason.
LOG_DIR="/Users/bearliu/Library/Logs/voice-daily-note"
LOG="$LOG_DIR/bookshelf_sync.log"
mkdir -p "$LOG_DIR"

cd "$PROJECT_DIR" || exit 1

OUT=$("$PYTHON" bookshelf_sync.py --batch 2>&1)
rc=$?   # capture before anything else clobbers $?

{
  echo "===== bookshelf_sync: $(date '+%Y-%m-%d %H:%M:%S %Z') ====="
  echo "$OUT"
  echo "===== Exit code: $rc ====="
  echo
} >> "$LOG" 2>&1

# Notify only when new bookshelf files were auto-created (the hallucination-risk path).
CREATED=$(echo "$OUT" | grep -oE '自动建档 [0-9]+ 个' | grep -oE '[0-9]+' | head -1)
if [ -n "$CREATED" ] && [ "$CREATED" -gt 0 ]; then
  osascript -e "display notification \"自动建档 ${CREATED} 个书架条目，请到 Books/Movies 逐条核对（中文标题可能撞同名英文作品）\" with title \"Bookshelf Sync · 待核对\" sound name \"Basso\""
fi

# Surface silent failure: launchd swallows it otherwise.
if [ "$rc" -ne 0 ]; then
  osascript -e "display notification \"bookshelf sync 失败 (exit $rc)，看 ~/Library/Logs/voice-daily-note/bookshelf_sync.log\" with title \"Voice Daily Note · 失败\" sound name \"Basso\""
fi
exit "$rc"
