#!/bin/bash
# send-message.sh -- Triple-channel cross-session messaging
#
# Uses THREE channels for maximum reliability:
#   1. Hook directive file (PreToolUse hook injects on next tool call -- MOST reliable)
#   2. File inbox (persistent record with metadata)
#   3. tmux send-keys (best-effort for real-time delivery)
#
# Usage:
#   ./send-message.sh <session> "message"
#   ./send-message.sh <session> @/path/to/file
#
# Environment:
#   MANAGER_DIR   -- Root directory for state/logs (default: script parent dir)
set -euo pipefail

SESSION="${1:?Usage: send-message.sh <session> <message|@file>}"
INPUT="${2:?Usage: send-message.sh <session> <message|@file>}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MANAGER_DIR="${MANAGER_DIR:-$SCRIPT_DIR}"
LOG_DIR="$MANAGER_DIR/logs"
LOG="$LOG_DIR/directives.log"

mkdir -p "$LOG_DIR"

# Load message from file if @prefix
if [[ "$INPUT" == @* ]]; then
    MESSAGE=$(cat "${INPUT:1}")
else
    MESSAGE="$INPUT"
fi

TS=$(date -Iseconds)
TS_FILE=$(date +%Y%m%d-%H%M%S)

# ---- Channel 1: Hook directive (reliable, automatic) ----
# A PreToolUse hook can pick this up on the agent's next tool call
# and inject it as additional context.
DIRECTIVE_DIR="$MANAGER_DIR/state/hooks"
mkdir -p "$DIRECTIVE_DIR"
DIRECTIVE_FILE="$DIRECTIVE_DIR/supervisor-directive-${SESSION}.json"
TEMP_FILE="${DIRECTIVE_FILE}.tmp"
cat > "$TEMP_FILE" << EOF
{
  "from": "manager",
  "to": "$SESSION",
  "timestamp": "$TS",
  "message": "$MESSAGE"
}
EOF
mv "$TEMP_FILE" "$DIRECTIVE_FILE"
echo "[$TS] HOOK -> $SESSION: directive written" >> "$LOG"

# ---- Channel 2: File inbox (persistent record) ----
INBOX="$MANAGER_DIR/state/directives/$SESSION/inbox"
mkdir -p "$INBOX"
MSG_FILE="$INBOX/${TS_FILE}.md"
cat > "$MSG_FILE" << EOF
---
from: manager
to: $SESSION
timestamp: $TS
---

$MESSAGE
EOF
echo "[$TS] FILE -> $SESSION: $MSG_FILE" >> "$LOG"

# ---- Channel 3: tmux send-keys (best-effort real-time) ----
if tmux has-session -t "$SESSION" 2>/dev/null; then
    # Clear any partial input first
    tmux send-keys -t "$SESSION" Escape 2>/dev/null || true
    sleep 0.2
    tmux send-keys -t "$SESSION" C-u 2>/dev/null || true
    sleep 0.2

    MSG_LEN=${#MESSAGE}
    if [ "$MSG_LEN" -lt 400 ]; then
        tmux send-keys -t "$SESSION" -l "$MESSAGE"
    else
        # Truncate long messages for tmux; full text is in file inbox
        SHORT="${MESSAGE:0:350}..."
        tmux send-keys -t "$SESSION" -l "$SHORT"
    fi
    sleep 0.2
    tmux send-keys -t "$SESSION" Enter
    echo "[$TS] TMUX -> $SESSION: sent (${MSG_LEN} chars)" >> "$LOG"
fi

echo "Message sent to $SESSION via hook + file + tmux"
