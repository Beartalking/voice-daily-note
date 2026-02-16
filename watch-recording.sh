#!/bin/bash
# Debounce wrapper for launchd file watcher.
# Called automatically when Recording/ directory changes.
#
# - Checks for audio files (wav/m4a/mp3)
# - Waits 30s for file transfers to complete
# - Runs pipeline.py
# - Logs to logs/watcher_YYYY-MM-DD.log
# - Sends macOS notification on completion

DIR="$(cd "$(dirname "$0")" && pwd)"
RECORDING_DIR="$DIR/Recording"
LOGS_DIR="$DIR/logs"
mkdir -p "$LOGS_DIR"

LOG="$LOGS_DIR/watcher_$(date +%Y-%m-%d).log"

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" >> "$LOG"
}

log "Watcher triggered — checking for audio files..."

# Check if any audio files exist in Recording/
shopt -s nullglob
AUDIO_FILES=("$RECORDING_DIR"/*.wav "$RECORDING_DIR"/*.m4a "$RECORDING_DIR"/*.mp3)
shopt -u nullglob

if [ ${#AUDIO_FILES[@]} -eq 0 ]; then
    log "No audio files found in Recording/. Skipping."
    exit 0
fi

log "Found ${#AUDIO_FILES[@]} audio file(s). Waiting 30s for transfers to finish..."
sleep 30

# Re-check after wait (files may have been moved/deleted)
shopt -s nullglob
AUDIO_FILES=("$RECORDING_DIR"/*.wav "$RECORDING_DIR"/*.m4a "$RECORDING_DIR"/*.mp3)
shopt -u nullglob

if [ ${#AUDIO_FILES[@]} -eq 0 ]; then
    log "Audio files disappeared after wait. Skipping."
    exit 0
fi

log "Processing ${#AUDIO_FILES[@]} audio file(s)..."

cd "$DIR"
python3 pipeline.py >> "$LOG" 2>&1
EXIT_CODE=$?

if [ $EXIT_CODE -eq 0 ]; then
    log "Pipeline completed successfully."
    osascript -e 'display notification "All done! Notes synced to Obsidian." with title "Voice Daily Note" sound name "Glass"'
else
    log "Pipeline finished with errors (exit code $EXIT_CODE)."
    osascript -e 'display notification "Pipeline finished with errors. Check logs." with title "Voice Daily Note" sound name "Basso"'
fi

exit $EXIT_CODE
