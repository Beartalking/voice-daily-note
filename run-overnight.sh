#!/bin/bash
# Run the voice daily note pipeline overnight.
# Usage: ./run-overnight.sh
#
# - Prevents Mac from sleeping while processing (caffeinate)
# - Logs everything to logs/YYYY-MM-DD_HHMMSS.log
# - Sends a macOS notification when done
# - Safe to close the terminal after launching

set -euo pipefail

DIR="$(cd "$(dirname "$0")" && pwd)"
LOGS_DIR="$DIR/logs"
mkdir -p "$LOGS_DIR"

TIMESTAMP=$(date +"%Y-%m-%d_%H%M%S")
LOG="$LOGS_DIR/$TIMESTAMP.log"

# Check API key
if [ -z "${ANTHROPIC_API_KEY:-}" ]; then
    echo "ERROR: ANTHROPIC_API_KEY not set."
    echo "Run: export ANTHROPIC_API_KEY='sk-ant-...'"
    exit 1
fi

echo "Starting overnight pipeline..."
echo "Log file: $LOG"
echo "You can close this terminal. Check the log or wait for the notification."

# nohup + caffeinate: keeps running after terminal closes, prevents sleep
nohup caffeinate -i bash -c "
    cd \"$DIR\"
    echo \"Pipeline started at \$(date)\" >> \"$LOG\"
    echo '========================================' >> \"$LOG\"

    python3 pipeline.py \"\$@\" >> \"$LOG\" 2>&1
    EXIT_CODE=\$?

    echo '' >> \"$LOG\"
    echo '========================================' >> \"$LOG\"
    echo \"Pipeline finished at \$(date) (exit code \$EXIT_CODE)\" >> \"$LOG\"

    # macOS notification
    if [ \$EXIT_CODE -eq 0 ]; then
        osascript -e 'display notification \"All done! Check output/ for your notes.\" with title \"Voice Daily Note\" sound name \"Glass\"'
    else
        osascript -e 'display notification \"Pipeline finished with errors. Check the log.\" with title \"Voice Daily Note\" sound name \"Basso\"'
    fi
" -- "$@" &

echo "Pipeline running in background (PID: $!)"
echo "Check progress: tail -f $LOG"
