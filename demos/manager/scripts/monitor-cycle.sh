#!/bin/bash
# monitor-cycle.sh -- Single monitoring cycle with full diagnostics
# Returns structured JSON for the manager session to act on.
#
# Usage:
#   MANAGED_SESSIONS="session-a session-b" ./monitor-cycle.sh
#   MANAGER_DIR=~/my-manager ./monitor-cycle.sh
#
# Environment:
#   MANAGER_DIR        -- Root directory for state/logs (default: script dir)
#   MANAGED_SESSIONS   -- Space-separated tmux session names (default: session-a session-b)
#   LOCK_FILE          -- Path to cluster lock JSON (default: $MANAGER_DIR/state/cluster-lock.json)
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MANAGER_DIR="${MANAGER_DIR:-$SCRIPT_DIR}"
LOCK_FILE="${LOCK_FILE:-$MANAGER_DIR/state/cluster-lock.json}"
LOG_DIR="$MANAGER_DIR/logs"
LOG_FILE="$LOG_DIR/supervisor.log"
CYCLE_FILE="$MANAGER_DIR/state/last-cycle.json"

# Sessions to monitor (space-separated)
MANAGED_SESSIONS="${MANAGED_SESSIONS:-session-a session-b}"

mkdir -p "$LOG_DIR" "$MANAGER_DIR/state"

log() { echo "[$(date +%H:%M:%S)] $*" | tee -a "$LOG_FILE"; }

# ---- State Detection ----

detect_state() {
    local f="$1"
    # Claude Code shows whimsical status words while thinking
    local thinking_words='Cerebrating|Levitating|Wandering|Symbioting|Cultivating|Fermenting|Wrangling|Herding|Combobulating|Frosting|Churned|Cooked|Brewed|Worked|Spelunking|Proofing|Crunched|Prestidigitating|Processing'

    if tail -15 "$f" | grep -qE "$thinking_words" 2>/dev/null; then
        local think_time
        think_time=$(tail -15 "$f" | grep -oP '\d+m \d+s|\d+s' 2>/dev/null | tail -1)
        # Check if it just FINISHED (past-tense words at prompt)
        if tail -5 "$f" | grep -q '>' 2>/dev/null; then
            if tail -10 "$f" | grep -qP '(Cooked|Brewed|Churned|Worked) for' 2>/dev/null; then
                echo "JUST_FINISHED|${think_time:-?}"
                return
            fi
        fi
        echo "THINKING|${think_time:-?}"
        return
    fi

    if tail -5 "$f" | grep -q '>' 2>/dev/null; then
        echo "AT_PROMPT|0s"
        return
    fi

    echo "UNKNOWN|0s"
}

# ---- Loop Detection ----
# Count repeated error patterns -- if the same error appears 3+ times,
# the agent is likely stuck in a loop.

detect_loop() {
    local f="$1"
    local top
    top=$(grep -oP 'Error:.*|FAIL:.*|TIMEOUT' "$f" 2>/dev/null | sort | uniq -c | sort -rn | head -1)
    local count
    count=$(echo "$top" | awk '{print $1}')
    if [ "${count:-0}" -ge 3 ]; then
        echo "LOOP|${count}|$(echo "$top" | sed 's/^[[:space:]]*[0-9]*//')"
    else
        echo "OK|0|"
    fi
}

# ---- Lock Staleness Check ----
# Reads the cluster lock file and checks if the current holder
# has exceeded the maximum hold time (30 minutes).

check_lock() {
    if [ ! -f "$LOCK_FILE" ]; then
        echo "FREE|0|none"
        return
    fi

    python3 -c "
import json, datetime as dt, sys
try:
    d = json.load(open('$LOCK_FILE'))
    lock = d.get('cluster_lock', d)
    h = lock.get('holder')
    if not h:
        print('FREE|0|none')
    else:
        acq = lock.get('acquired_at', '')
        try:
            t = dt.datetime.fromisoformat(acq.replace('+00:00Z','Z').rstrip('Z')).replace(tzinfo=dt.timezone.utc)
            age = int((dt.datetime.now(dt.timezone.utc) - t).total_seconds() / 60)
        except Exception:
            age = 0
        stale = 'STALE' if age > 30 else 'OK'
        print(f'{stale}|{age}|{h}')
except Exception:
    print('ERROR|0|unknown')
" 2>/dev/null || echo "ERROR|0|unknown"
}

# ---- Activity Extraction ----

get_activity() {
    local f="$1"
    local n="${2:-3}"
    tail -30 "$f" | grep -E '[*]|>' | tail -"$n" | sed 's/^[[:space:]]*//' | head -"$n"
}

# ====== Main ======

LOCK_STATUS=$(check_lock)
IFS='|' read -r L_STATUS L_AGE L_HOLDER <<< "$LOCK_STATUS"

ISSUES=""
SESSION_RESULTS=""
TS=$(date -Iseconds)

for session in $MANAGED_SESSIONS; do
    # Capture tmux pane
    capture="/tmp/${session}-capture.txt"
    tmux capture-pane -t "$session" -p -S -150 > "$capture" 2>/dev/null || true

    STATE_RAW=$(detect_state "$capture")
    LOOP_RAW=$(detect_loop "$capture")

    IFS='|' read -r S_STATE S_TIME <<< "$STATE_RAW"
    IFS='|' read -r S_LOOP S_LOOP_COUNT S_LOOP_ERR <<< "$LOOP_RAW"

    log "CYCLE: $session=$S_STATE($S_TIME) loop=$S_LOOP"

    # Detect issues
    [ "$S_STATE" = "AT_PROMPT" ] && ISSUES="${ISSUES}${session}_idle,"
    [ "$S_LOOP" = "LOOP" ] && ISSUES="${ISSUES}${session}_loop,"
    [ "${S_TIME%%m*}" -gt 25 ] 2>/dev/null && ISSUES="${ISSUES}${session}_long_think,"

    # Append to JSON result
    SESSION_RESULTS="${SESSION_RESULTS}\"$session\": {\"state\": \"$S_STATE\", \"time\": \"$S_TIME\", \"loop\": \"$S_LOOP\", \"loop_count\": ${S_LOOP_COUNT:-0}},"

    # Print line
    printf "  %-12s %-15s %-8s\n" "${session}:" "$S_STATE($S_TIME)" "$S_LOOP"
done

# Check lock staleness
[ "$L_STATUS" = "STALE" ] && ISSUES="${ISSUES}lock_stale,"

# Write cycle result
cat > "$CYCLE_FILE" << EOF
{
  "timestamp": "$TS",
  ${SESSION_RESULTS}
  "lock": {"status": "$L_STATUS", "holder": "$L_HOLDER", "age_min": $L_AGE},
  "issues": "${ISSUES%,}"
}
EOF

# Print summary
echo "==========================================="
echo "  MONITOR CYCLE $(date +%H:%M:%S)"
echo "==========================================="
for session in $MANAGED_SESSIONS; do
    capture="/tmp/${session}-capture.txt"
    STATE_RAW=$(detect_state "$capture")
    LOOP_RAW=$(detect_loop "$capture")
    IFS='|' read -r S_STATE S_TIME <<< "$STATE_RAW"
    IFS='|' read -r S_LOOP _ _ <<< "$LOOP_RAW"
    printf "  %-12s %-15s %-8s\n" "${session}:" "$S_STATE($S_TIME)" "$S_LOOP"
done
echo "  LOCK: $L_STATUS holder=$L_HOLDER age=${L_AGE}m"
[ -n "$ISSUES" ] && echo "  ISSUES: $ISSUES" || echo "  ISSUES: none"
echo "==========================================="
