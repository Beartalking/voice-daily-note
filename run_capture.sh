#!/bin/bash
# launchd: com.bear.voice-capture — fired daily at 09:00 and 21:00.
# Pipeline A: ~/Desktop/capture/ audio -> transcribe -> refine -> Obsidian Daily Notes
# -> archive (also runs text inbox as Step 2.6). This is step 1 of /capture only;
# voice-capture triage (step 2) needs Claude + the Reminders MCP and stays manual:
# a later /capture finds no audio left and goes straight to triage.
# Each run sits 30 min after a Plaud sync (08:30 / 20:30, drops dictation into
# capture/). The 09:00 run sits before text inbox (09:30). Overlap with a manual /capture is safe: pipeline.py holds
# .pipeline.lock and the loser prints [LOCKED] and exits 0.
# Manual: bash run_capture.sh

PROJECT_DIR="/Users/bearliu/Desktop/ClaudeCode/voice-daily-note"
PYTHON="/usr/bin/python3"
# The whisper fallback shells out to ffmpeg (Homebrew); launchd's PATH lacks it.
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin"
# Logs live outside the Desktop tree — see run_bookshelf_sync.sh for why.
LOG_DIR="/Users/bearliu/Library/Logs/voice-daily-note"
LOG="$LOG_DIR/capture.log"
mkdir -p "$LOG_DIR"

cd "$PROJECT_DIR" || exit 1

# caffeinate: transcription can run for minutes per file; don't let the Mac idle-sleep mid-run.
OUT=$(caffeinate -i "$PYTHON" pipeline.py 2>&1)
rc=$?   # capture before anything else clobbers $?

{
  echo "===== capture: $(date '+%Y-%m-%d %H:%M:%S %Z') ====="
  echo "$OUT"
  echo "===== Exit code: $rc ====="
  echo
} >> "$LOG" 2>&1

notify() {
  osascript -e "display notification \"$1\" with title \"$2\" sound name \"$3\""
}

# Unparseable filenames are skipped with one printed line and no failure count
# (e.g. 2026_09_18_06_51_59.wav). Nobody reads the output of a scheduled run, so say it.
SKIPPED=$(echo "$OUT" | sed -n 's/.*Skipped \([0-9][0-9]*\) files (no timestamp in name).*/\1/p' | head -1)
ARCHIVED=$(echo "$OUT" | sed -n 's/.*Archived *: \([0-9][0-9]*\) files.*/\1/p' | head -1)

if [ "$rc" -ne 0 ]; then
  notify "capture 有步骤失败 (exit $rc)，看 ~/Library/Logs/voice-daily-note/capture.log" "Voice Capture · 失败" "Basso"
elif [ -n "$ARCHIVED" ] && [ "$(date +%H)" -lt 12 ]; then
  # Evening run stays quiet on success; the morning one is the nudge to triage.
  notify "$ARCHIVED 段录音已写进日记，开会话跑 /capture 做分诊" "Voice Capture · 已转录" "Glass"
fi
if [ -n "$SKIPPED" ]; then
  notify "$SKIPPED 个音频文件名认不出时间戳，被跳过，还在 capture/ 里" "Voice Capture · 有文件被跳过" "Basso"
fi
exit $rc
