#!/bin/bash
# poll-sessions.sh -- Capture and analyze managed Claude Code sessions
# Returns JSON state for the manager supervisor to act on.
#
# Usage:
#   MANAGED_SESSIONS="session-a session-b" ./poll-sessions.sh
#
# Environment:
#   MANAGER_DIR        -- Root directory for state/logs (default: script parent dir)
#   MANAGED_SESSIONS   -- Space-separated tmux session names (default: session-a session-b)
#   LOCK_FILE          -- Path to cluster lock JSON (default: $MANAGER_DIR/state/cluster-lock.json)
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MANAGER_DIR="${MANAGER_DIR:-$SCRIPT_DIR}"
STATE_FILE="$MANAGER_DIR/state/sessions.json"
LOG_DIR="$MANAGER_DIR/logs"
LOG_FILE="$LOG_DIR/supervisor.log"
LOCK_FILE="${LOCK_FILE:-$MANAGER_DIR/state/cluster-lock.json}"

# Sessions to monitor (space-separated)
MANAGED_SESSIONS="${MANAGED_SESSIONS:-session-a session-b}"

mkdir -p "$LOG_DIR" "$MANAGER_DIR/state"

log() { echo "[$(date +%H:%M:%S)] $*" | tee -a "$LOG_FILE"; }

# ---- Capture a tmux session's visible output ----

capture_session() {
    local session="$1"
    local outfile="/tmp/${session}-capture.txt"
    tmux capture-pane -t "$session" -p -S -150 > "$outfile" 2>/dev/null || true
    echo "$outfile"
}

# ---- Detect session state from captured output ----

detect_state() {
    local f="$1"

    # Check for Claude Code thinking indicators FIRST
    # (the prompt character may appear below the thinking line)
    local thinking_words='Cerebrating|Levitating|Wandering|Symbioting|Cultivating|Fermenting|Wrangling|Herding|Combobulating|Frosting|Churned|Cooked|Brewed|Worked'
    if tail -15 "$f" | grep -qE "$thinking_words" 2>/dev/null; then
        local think_time
        think_time=$(tail -15 "$f" | grep -oP '\d+m \d+s|\d+s' 2>/dev/null | tail -1)
        # Check if it just FINISHED (past-tense status + prompt visible)
        if tail -5 "$f" | grep -q '>' 2>/dev/null; then
            if tail -10 "$f" | grep -qP '(Cooked|Brewed|Churned|Worked) for' 2>/dev/null; then
                echo "JUST_FINISHED:$think_time"
                return
            fi
        fi
        echo "THINKING:$think_time"
        return
    fi

    # Check if at prompt (idle)
    if tail -5 "$f" | grep -q '>' 2>/dev/null; then
        echo "AT_PROMPT"
        return
    fi

    # Check if running a test or command
    if tail -20 "$f" | grep -qE 'timeout.*[0-9]m|Running\.\.\.|BUILD|deploying|kubectl' 2>/dev/null; then
        echo "RUNNING_TEST"
        return
    fi

    # Check for crashes
    if tail -20 "$f" | grep -qE 'SIGSEGV|Segmentation|CRASHED|Error:.*fatal' 2>/dev/null; then
        echo "CRASHED"
        return
    fi

    echo "UNKNOWN"
}

# ---- Detect error loops ----

detect_loop() {
    local f="$1"
    local repeated
    repeated=$(grep -oP 'Error:.*|FAIL:.*' "$f" 2>/dev/null | sort | uniq -c | sort -rn | head -1)
    local count
    count=$(echo "$repeated" | awk '{print $1}')
    if [ "${count:-0}" -ge 3 ]; then
        echo "LOOP_DETECTED:$repeated"
    else
        echo "OK"
    fi
}

# ---- Check cluster lock staleness ----

check_lock_staleness() {
    if [ ! -f "$LOCK_FILE" ]; then
        echo "FREE"
        return
    fi

    local acquired
    acquired=$(python3 -c "
import json, sys
try:
    d = json.load(open('$LOCK_FILE'))
    lock = d.get('cluster_lock', d)
    print(lock.get('acquired_at', '') or '')
except Exception:
    print('')
" 2>/dev/null)

    if [ -z "$acquired" ]; then
        echo "FREE"
        return
    fi

    local age_min
    age_min=$(python3 -c "
from datetime import datetime, timezone
acquired = '$acquired'.replace('+00:00Z','Z').rstrip('Z')
try:
    t = datetime.fromisoformat(acquired).replace(tzinfo=timezone.utc)
except Exception:
    t = datetime.strptime(acquired, '%Y-%m-%dT%H:%M:%S.%f').replace(tzinfo=timezone.utc)
now = datetime.now(timezone.utc)
print(int((now - t).total_seconds() / 60))
" 2>/dev/null || echo "0")

    local holder
    holder=$(python3 -c "
import json
d = json.load(open('$LOCK_FILE'))
lock = d.get('cluster_lock', d)
print(lock.get('holder') or 'none')
" 2>/dev/null || echo "unknown")

    if [ "$age_min" -gt 30 ]; then
        echo "STALE:${holder}:${age_min}min"
    else
        echo "OK:${holder}:${age_min}min"
    fi
}

# ====== Main ======

log "=== Poll cycle ==="

LOCK_STATUS=$(check_lock_staleness)
log "LOCK: $LOCK_STATUS"

# Build JSON output
echo "{"

first=true
for session in $MANAGED_SESSIONS; do
    capture_file=$(capture_session "$session")
    state=$(detect_state "$capture_file")
    loop=$(detect_loop "$capture_file")

    log "${session}: state=$state loop=$loop"

    if [ "$first" = true ]; then
        first=false
    else
        echo ","
    fi
    echo "  \"${session}_state\": \"$state\","
    echo "  \"${session}_loop\": \"$loop\""
done

echo ","
echo "  \"lock_status\": \"$LOCK_STATUS\""
echo "}"
