#!/bin/bash
# active-supervisor.sh — Actively monitors and guides the RDMA agent
# Uses multi-LLM tools, institutional knowledge, and session context
# Intervenes when stuck, sends corrective directives, tracks progress
#
# Usage: ./active-supervisor.sh [--interval 300] [--session session-b]

set -euo pipefail

INTERVAL="${1:-300}"
SESSION="${2:-session-b}"
STACK_ROOT="<HPC_STACK_ROOT>"
SUP_DIR="$STACK_ROOT/supervisor"
QM="$STACK_ROOT/scripts/multi-model/query-model.sh"
EC="$STACK_ROOT/mcp-servers/email-access/email-cli.sh"
INJECT="$STACK_ROOT/whatsapp-agents/scripts/inject-command.sh"
LEARNINGS="$STACK_ROOT/docs/AGENT_LEARNINGS.md"
CYCLE=0
STUCK_COUNT=0
LAST_MAX_TOKEN=0
LAST_CQ_ERR=0

log() { echo "[$(date +%H:%M:%S)] $*" | tee -a "$SUP_DIR/logs/active-supervisor.log"; }

capture_session() {
    tmux capture-pane -t "$SESSION" -p -S -100 > /tmp/rdma-capture-latest.txt 2>/dev/null
    echo /tmp/rdma-capture-latest.txt
}

extract_metrics() {
    local f="$1"
    local ok=$(grep -c 'ok=1\|OK\b' "$f" 2>/dev/null || echo 0)
    local timeouts=$(grep -c 'SENTINEL-TIMEOUT\|TIMEOUT' "$f" 2>/dev/null || echo 0)
    local cq_err=$(grep -c 'CQ err\|prov_errno\|Bad QP' "$f" 2>/dev/null || echo 0)
    local recv=$(grep -c 'Received\|STAGING-COPY' "$f" 2>/dev/null || echo 0)
    local max_token=$(grep -oP 'token=\K[0-9]+' "$f" 2>/dev/null | sort -n | tail -1)
    echo "ok=$ok timeouts=$timeouts cq_err=$cq_err recv=$recv max_token=${max_token:-0}"
}

detect_state() {
    local f="$1"

    # Check if agent is thinking
    if grep -qE 'Cerebrating|Levitating|Wandering|Symbioting|Cultivating|Fermenting|Wrangling|Herding|Cooked|Brewed|Baked|Sautéed' "$f" 2>/dev/null; then
        echo "THINKING"
        return
    fi

    # Check if at prompt
    if tail -3 "$f" | grep -q '❯' 2>/dev/null; then
        echo "AT_PROMPT"
        return
    fi

    # Check if running a test
    if grep -qE 'Running\.\.\.|timeout.*[0-9]m|BUILD' "$f" 2>/dev/null; then
        echo "RUNNING_TEST"
        return
    fi

    # Check if crashed
    if grep -qE 'SIGSEGV\|Segmentation\|signal 11\|CRASHED' "$f" 2>/dev/null; then
        echo "CRASHED"
        return
    fi

    echo "UNKNOWN"
}

check_progress() {
    local metrics="$1"
    local max_token=$(echo "$metrics" | grep -oP 'max_token=\K[0-9]+')
    local cq_err=$(echo "$metrics" | grep -oP 'cq_err=\K[0-9]+')

    if [ "${max_token:-0}" -gt "$LAST_MAX_TOKEN" ]; then
        log "PROGRESS: max_token improved $LAST_MAX_TOKEN → $max_token"
        STUCK_COUNT=0
        LAST_MAX_TOKEN="$max_token"
        return 0
    fi

    if [ "${cq_err:-0}" -lt "$LAST_CQ_ERR" ] && [ "$LAST_CQ_ERR" -gt 0 ]; then
        log "PROGRESS: CQ errors reduced $LAST_CQ_ERR → $cq_err"
        STUCK_COUNT=0
        LAST_CQ_ERR="$cq_err"
        return 0
    fi

    LAST_CQ_ERR="${cq_err:-0}"
    STUCK_COUNT=$((STUCK_COUNT + 1))

    if [ "$STUCK_COUNT" -ge 6 ]; then
        log "STUCK: No progress for $((STUCK_COUNT * INTERVAL / 60)) minutes"
        return 1
    fi

    return 0
}

send_guidance() {
    local metrics="$1"
    local state="$2"
    local capture="$3"

    # Get recent errors from the capture
    local errors=$(grep -E 'prov_errno|CQ err|Error|FAIL|crash' "$capture" 2>/dev/null | tail -5)
    local recent=$(tail -20 "$capture" 2>/dev/null)

    # Search institutional knowledge
    local knowledge=$(grep -i "prov_errno\|staging\|MR.*reg\|buffer_size\|fi_writemsg" "$LEARNINGS" 2>/dev/null | head -5)

    # Build focused prompt for Gemini
    cat > /tmp/supervisor-active-prompt.md << PROMPT
You are supervising an RDMA debugging agent. Based on the evidence below, provide ONE specific directive (max 3 sentences).

METRICS: $metrics
STATE: $state
STUCK_COUNT: $STUCK_COUNT cycles without progress

RECENT ERRORS:
$errors

RECENT AGENT OUTPUT:
$(echo "$recent" | tail -10)

INSTITUTIONAL KNOWLEDGE:
$knowledge

RULES:
- If prov_errno=7: the MR doesn't cover the write target address. Expand MR or fix offset calculation.
- If prov_errno=5: LKEY invalid. Re-register MR on the correct buffer.
- If CQ errors but data flows: handle errors gracefully, don't abort on first error.
- If agent is thinking >30min: it may be stuck in analysis paralysis. Send "implement the smallest fix and test."
- If no test has run in 30min: send "build, deploy, and run the benchmark now."
- Never suggest anything on the BANLIST.

Respond with ONLY the directive text (no preamble). Max 3 sentences.
PROMPT

    source <HOME>/.env.local_deployment 2>/dev/null
    local directive=$($QM gemini-3-pro @/tmp/supervisor-active-prompt.md 2>/dev/null | head -5)

    if [ -n "$directive" ]; then
        log "DIRECTIVE: $directive"
        $INJECT "$SESSION" "$directive" 2>/dev/null
        echo "$directive" >> "$SUP_DIR/learnings/directives-sent.md"
    fi
}

# Initialize
log "Active supervisor starting: session=$SESSION interval=${INTERVAL}s"
mkdir -p "$SUP_DIR/logs" "$SUP_DIR/learnings"
touch "$SUP_DIR/learnings/directives-sent.md"

# Main loop
while true; do
    CYCLE=$((CYCLE + 1))

    CAPTURE=$(capture_session)
    METRICS=$(extract_metrics "$CAPTURE")
    STATE=$(detect_state "$CAPTURE")

    log "Cycle $CYCLE: $METRICS state=$STATE stuck=$STUCK_COUNT"

    # Check if making progress
    if ! check_progress "$METRICS"; then
        # Stuck — intervene
        log "Intervening (stuck $STUCK_COUNT cycles)..."
        send_guidance "$METRICS" "$STATE" "$CAPTURE"
    fi

    # If agent has been thinking >30min, nudge it
    THINK_TIME=$(grep -oP '(\d+)m \d+s' "$CAPTURE" 2>/dev/null | tail -1 | grep -oP '^\d+')
    if [ "${THINK_TIME:-0}" -gt 30 ] && [ "$STATE" = "THINKING" ]; then
        log "Agent thinking ${THINK_TIME}m — nudging"
        $INJECT "$SESSION" "You've been thinking for ${THINK_TIME} minutes. Pick the simplest approach and implement it now. Build, deploy, test." 2>/dev/null
    fi

    # Update timeline
    echo "## Cycle $CYCLE — $(date -Iseconds)" >> "$SUP_DIR/learnings/timeline.md"
    echo "Metrics: $METRICS | State: $STATE | Stuck: $STUCK_COUNT" >> "$SUP_DIR/learnings/timeline.md"
    echo "" >> "$SUP_DIR/learnings/timeline.md"

    sleep "$INTERVAL"
done
