#!/bin/bash
# supervisor/monitor.sh — Continuous RDMA session monitor + learning loop
# Captures tmux output, extracts key events, dispatches to multi-LLM for analysis
# Updates learnings file and sends corrective prompts to the RDMA agent
#
# Usage: ./monitor.sh [--interval 300] [--session session-b]

set -euo pipefail

INTERVAL="${1:-300}"  # seconds between cycles
SESSION="${2:-session-b}"
STACK_ROOT="<HPC_STACK_ROOT>"
SUP_DIR="$STACK_ROOT/supervisor"
QM="$STACK_ROOT/scripts/multi-model/query-model.sh"
CYCLE=0

log() { echo "[$(date +%H:%M:%S)] $*" | tee -a "$SUP_DIR/logs/supervisor.log"; }

capture_session() {
    local ts=$(date +%Y%m%d-%H%M%S)
    local outfile="$SUP_DIR/logs/capture-${ts}.txt"
    tmux capture-pane -t "$SESSION" -p -S -200 > "$outfile" 2>/dev/null
    echo "$outfile"
}

extract_events() {
    local capture="$1"
    # Extract key events: errors, timeouts, OK tokens, builds, CQ errors, fixes
    grep -E "SENTINEL-TIMEOUT|OK.*token|CQ err|prov_errno|Bad QP|BUILD|Received|DISPATCH|COMBINE|fi_sendmsg|fi_recvmsg|MR re-reg|FABRIC|SIGSEGV|crash|fix|Error|EAGAIN|token=" "$capture" 2>/dev/null | tail -30
}

extract_metrics() {
    local capture="$1"
    local ok timeouts cq_err recv max_token

    ok=$(awk 'BEGIN{c=0} /ok=1|OK/{c++} END{print c}' "$capture" 2>/dev/null)
    timeouts=$(awk 'BEGIN{c=0} /SENTINEL-TIMEOUT|TIMEOUT/{c++} END{print c}' "$capture" 2>/dev/null)
    cq_err=$(awk 'BEGIN{c=0} /CQ err|prov_errno|Bad QP/{c++} END{print c}' "$capture" 2>/dev/null)
    recv=$(awk 'BEGIN{c=0} /Received/{c++} END{print c}' "$capture" 2>/dev/null)
    max_token=$(awk 'match($0,/token=([0-9]+)/,m){ if (m[1] > max) max=m[1] } END{ print (max ? max : 0) }' "$capture" 2>/dev/null)

    echo "ok=${ok:-0} timeouts=${timeouts:-0} cq_err=${cq_err:-0} recv=${recv:-0} max_token=${max_token:-0}"
}

detect_patterns() {
    local capture="$1"
    local patterns=""

    # Detect stuck loops
    local repeated=$(grep "SENTINEL-TIMEOUT" "$capture" 2>/dev/null | sort | uniq -c | sort -rn | head -1 | awk '{print $1}')
    if [ "${repeated:-0}" -gt 50 ]; then
        patterns="$patterns STUCK_LOOP(${repeated}x_same_timeout)"
    fi

    # Detect crashes
    if grep -q "SIGSEGV\|Segmentation\|abort\|signal 11" "$capture" 2>/dev/null; then
        patterns="$patterns CRASH_DETECTED"
    fi

    # Detect build failures
    if grep -q "BUILD.*FAIL\|error:.*undefined\|fatal error" "$capture" 2>/dev/null; then
        patterns="$patterns BUILD_FAILURE"
    fi

    # Detect agent thinking too long
    if grep -q "Cerebrating.*[3-9][0-9]m\|Cerebrating.*[1-9][0-9][0-9]m" "$capture" 2>/dev/null; then
        patterns="$patterns LONG_THINKING"
    fi

    # Detect repeated same approach
    local approach_count=$(grep -c "Let me try\|Let me test\|Rebuild and test" "$capture" 2>/dev/null || echo 0)
    if [ "$approach_count" -gt 5 ]; then
        patterns="$patterns REPEATED_CYCLES($approach_count)"
    fi

    echo "${patterns:-NORMAL}"
}

update_learnings() {
    local cycle="$1"
    local metrics="$2"
    local patterns="$3"
    local events="$4"
    local ts=$(date +%Y-%m-%dT%H:%M:%S)

    cat >> "$SUP_DIR/learnings/timeline.md" << EOF

## Cycle $cycle — $ts
**Metrics:** $metrics
**Patterns:** $patterns
**Key Events:**
\`\`\`
$(echo "$events" | tail -15)
\`\`\`

EOF
}

dispatch_analysis() {
    local metrics="$1"
    local patterns="$2"
    local events="$3"
    local learnings_file="$SUP_DIR/learnings/timeline.md"
    local prev_learnings=""

    if [ -f "$learnings_file" ]; then
        prev_learnings=$(tail -100 "$learnings_file")
    fi

    # Build focused, grounded prompt
    cat > /tmp/supervisor-prompt.md << PROMPT
<role>You are supervising an autonomous RDMA/DeepEP debugging session. The only finish line is a passing DeepEP benchmark. Stay benchmark-first and architecture-aware.</role>

<current_metrics>
$metrics
</current_metrics>

<detected_patterns>
$patterns
</detected_patterns>

<recent_events>
$(echo "$events" | tail -20)
</recent_events>

<previous_learnings>
$(echo "$prev_learnings" | tail -50)
</previous_learnings>

<grounded_architecture>
Python benchmark -> DeepEP runtime (deep_ep.cpp) -> EFA proxy (efa_proxy.cpp / libfabric) -> NCCL metadata exchange -> remote apply -> CUDA dispatch/combine kernels (internode.cu).
Known-good reference patterns live in aws-ofi-nccl files under <HOME>/<project>.
</grounded_architecture>

<known_good_progress>
- Pod bring-up works with hostNetwork=true.
- GPU and EFA device visibility work.
- Process startup works.
- Local fabric init gets far enough to exchange metadata.
- NCCL metadata exchange works.
- At least one dispatch-phase barrier bug was already fixed in an earlier run.
</known_good_progress>

<supervisor_rules>
- Do not suggest broad redesign unless the current layer is clearly falsified.
- Prefer the smallest stabilizing experiment over new theories.
- Treat tmux/log evidence as ground truth.
- When stuck, tell the agent to prove one thing at a time.
- Avoid generic EFA folklore unless directly tied to the current failure line.
</supervisor_rules>

<instructions>
1. Is the agent making benchmark progress or stuck?
2. What is the most likely active blocker from the recent events?
3. What is the smallest next corrective prompt to send (max 3 sentences)?
4. What single learning should be added to the log?

Respond in this exact format:
STATUS: [PROGRESSING|STUCK|DIVERGING|CRASHED]
DIAGNOSIS: [one line]
DIRECTIVE: [max 3 sentences to paste into the agent's tmux session]
LEARNING: [one line to add to learnings]
</instructions>
PROMPT

    # Use fast model for supervisor analysis
    $QM gemini-3-pro @/tmp/supervisor-prompt.md 2>/dev/null
}

send_directive() {
    local directive="$1"
    if [ -n "$directive" ] && [ "$directive" != "none" ] && [ "$directive" != "N/A" ]; then
        log "SENDING DIRECTIVE: $directive"
        tmux send-keys -t "$SESSION" "$directive" Enter
    fi
}

# Initialize
log "Supervisor starting: session=$SESSION interval=${INTERVAL}s"
echo "# RDMA Agent Supervision Timeline" > "$SUP_DIR/learnings/timeline.md"
echo "" >> "$SUP_DIR/learnings/timeline.md"
echo "Started: $(date -Iseconds)" >> "$SUP_DIR/learnings/timeline.md"

# Main loop
while true; do
    CYCLE=$((CYCLE + 1))
    log "=== Cycle $CYCLE ==="

    # 1. Capture current state
    CAPTURE=$(capture_session)
    log "Captured: $CAPTURE"

    # 2. Extract events and metrics
    EVENTS=$(extract_events "$CAPTURE")
    METRICS=$(extract_metrics "$CAPTURE")
    PATTERNS=$(detect_patterns "$CAPTURE")
    log "Metrics: $METRICS"
    log "Patterns: $PATTERNS"

    # 3. Update learnings
    update_learnings "$CYCLE" "$METRICS" "$PATTERNS" "$EVENTS"

    # 4. If abnormal patterns detected, dispatch to LLM for analysis
    if echo "$PATTERNS" | grep -qv "NORMAL"; then
        log "Abnormal pattern detected, dispatching analysis..."
        ANALYSIS=$(dispatch_analysis "$METRICS" "$PATTERNS" "$EVENTS")

        if [ -n "$ANALYSIS" ]; then
            # Parse the response
            STATUS=$(echo "$ANALYSIS" | grep "^STATUS:" | head -1 | sed 's/STATUS: *//')
            DIAGNOSIS=$(echo "$ANALYSIS" | grep "^DIAGNOSIS:" | head -1 | sed 's/DIAGNOSIS: *//')
            DIRECTIVE=$(echo "$ANALYSIS" | grep "^DIRECTIVE:" | head -1 | sed 's/DIRECTIVE: *//')
            LEARNING=$(echo "$ANALYSIS" | grep "^LEARNING:" | head -1 | sed 's/LEARNING: *//')

            log "Status: $STATUS"
            log "Diagnosis: $DIAGNOSIS"

            # Save analysis
            echo "### LLM Analysis (Cycle $CYCLE)" >> "$SUP_DIR/learnings/timeline.md"
            echo "- Status: $STATUS" >> "$SUP_DIR/learnings/timeline.md"
            echo "- Diagnosis: $DIAGNOSIS" >> "$SUP_DIR/learnings/timeline.md"
            echo "- Learning: $LEARNING" >> "$SUP_DIR/learnings/timeline.md"
            echo "" >> "$SUP_DIR/learnings/timeline.md"

            # Send corrective directive if agent is stuck or diverging
            if echo "$STATUS" | grep -qiE "STUCK|DIVERGING|CRASHED"; then
                send_directive "$DIRECTIVE"
            fi
        fi
    else
        log "Normal operation, no intervention needed"
    fi

    # 5. Every 5 cycles, do a deep analysis with multi-model
    if [ $((CYCLE % 60)) -eq 0 ]; then
        log "Deep analysis cycle (every 5th)"
        # Summarize all learnings so far
        SUMMARY=$(cat "$SUP_DIR/learnings/timeline.md" | tail -200)
        echo "$SUMMARY" | $QM gemini-3-pro - > "$SUP_DIR/learnings/deep-analysis-cycle${CYCLE}.md" 2>/dev/null &
    fi

    log "Sleeping ${INTERVAL}s..."
    sleep "$INTERVAL"
done
