#!/bin/bash
# bolt-supervisor-v3.sh — CUCo-enhanced Bolt state-machine supervisor
#
# Extends v2 with:
#   - CUCo design-space advisor for stuck-state diagnostics
#   - Pre-deploy gate (L0/L1) before sending build/deploy directives
#   - Tried-suggestions tracking to avoid repeating failed alternatives
#   - --dry-run mode for logging without sending directives
#
# Usage:
#   ./bolt-supervisor-v3.sh [session] [interval_seconds] [--dry-run]
#   ./bolt-supervisor-v3.sh rdma 90
#   ./bolt-supervisor-v3.sh rdma 90 --dry-run
set -euo pipefail

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
SESSION="${1:-session-b}"
INTERVAL="${2:-90}"
DRY_RUN=false

# Check for --dry-run anywhere in args
for arg in "$@"; do
    if [ "$arg" = "--dry-run" ]; then
        DRY_RUN=true
    fi
done

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INJECT="<HPC_STACK_ROOT>/whatsapp-agents/scripts/inject-command.sh"
LOG="${SCRIPT_DIR}/logs/bolt-v3.log"
TRIED_LOG="${SCRIPT_DIR}/logs/tried-suggestions.log"
CUCO_ADVISOR="${SCRIPT_DIR}/cuco-advisor.py"
PRE_DEPLOY_GATE="${SCRIPT_DIR}/pre-deploy-gate.sh"

mkdir -p "$(dirname "$LOG")"

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
log() { echo "[$(date +%H:%M:%S)] $*" | tee -a "$LOG"; }
log_cuco() { echo "[$(date +%H:%M:%S)] [CUCO] $*" | tee -a "$LOG"; }

# ---------------------------------------------------------------------------
# State tracking
# ---------------------------------------------------------------------------
CYCLE=0
LAST_DIRECTIVE=""
LAST_STATE=""
SAME_STATE_COUNT=0
STUCK_THRESHOLD=3  # cycles in same state before invoking CUCo advisor

log "Bolt Supervisor v3 starting: session=$SESSION interval=${INTERVAL}s dry_run=$DRY_RUN"
log "CUCo advisor: $CUCO_ADVISOR"
log "Pre-deploy gate: $PRE_DEPLOY_GATE"

# Initialize tried-suggestions log if it doesn't exist
if [ ! -f "$TRIED_LOG" ]; then
    echo "# Tried CUCo suggestions — format: TIMESTAMP | STATE | DIMENSION | VALUE" > "$TRIED_LOG"
fi

# ---------------------------------------------------------------------------
# Helper: check if a suggestion has already been tried
# ---------------------------------------------------------------------------
is_tried() {
    local state="$1"
    local dim="$2"
    local value="$3"
    grep -qF "${state}|${dim}|${value}" "$TRIED_LOG" 2>/dev/null
}

# ---------------------------------------------------------------------------
# Helper: record a suggestion as tried
# ---------------------------------------------------------------------------
mark_tried() {
    local state="$1"
    local dim="$2"
    local value="$3"
    echo "$(date -Iseconds) | ${state} | ${dim} | ${value}" >> "$TRIED_LOG"
}

# ---------------------------------------------------------------------------
# Helper: run CUCo advisor and extract suggestions
# ---------------------------------------------------------------------------
run_cuco_advisor() {
    local state="$1"
    local has_timeout="$2"

    if [ ! -f "$CUCO_ADVISOR" ]; then
        log_cuco "Advisor script not found: $CUCO_ADVISOR"
        return 1
    fi

    local advisor_args=(python3 "$CUCO_ADVISOR" --state "$state" --json)
    if [ "$has_timeout" = "true" ]; then
        advisor_args+=(--timeout)
    fi

    local result
    result=$("${advisor_args[@]}" 2>/dev/null) || {
        log_cuco "Advisor failed for state=$state"
        return 1
    }

    echo "$result"
}

# ---------------------------------------------------------------------------
# Helper: extract untried suggestion from advisor JSON
# ---------------------------------------------------------------------------
get_untried_suggestion() {
    local state="$1"
    local advisor_json="$2"

    python3 -c "
import sys, json

data = json.loads('''$advisor_json''')
failing_dim = data.get('failing_dimension')
if not failing_dim:
    sys.exit(1)

suggestions = data.get('suggestions', [])
for s in suggestions:
    value = s.get('value', s) if isinstance(s, dict) else s
    # Output: dim|value|description
    desc = s.get('description', '') if isinstance(s, dict) else ''
    print(f'{failing_dim}|{value}|{desc}')
" 2>/dev/null || true
}

# ---------------------------------------------------------------------------
# Helper: run pre-deploy gate on a .cu file
# ---------------------------------------------------------------------------
run_pre_deploy_gate() {
    local cu_file="$1"

    if [ ! -f "$PRE_DEPLOY_GATE" ]; then
        log_cuco "Pre-deploy gate not found: $PRE_DEPLOY_GATE"
        return 1
    fi

    if [ ! -f "$cu_file" ]; then
        log_cuco "Candidate file not found: $cu_file"
        return 1
    fi

    log_cuco "Running pre-deploy gate on: $cu_file"
    if bash "$PRE_DEPLOY_GATE" "$cu_file" 2>&1 | tee -a "$LOG"; then
        log_cuco "Pre-deploy gate PASSED"
        return 0
    else
        log_cuco "Pre-deploy gate FAILED — blocking deploy directive"
        return 1
    fi
}

# ---------------------------------------------------------------------------
# Helper: send directive (respects --dry-run)
# ---------------------------------------------------------------------------
send_directive() {
    local directive="$1"

    if [ "$DRY_RUN" = true ]; then
        log "[DRY-RUN] Would send directive: $directive"
    else
        log ">>> DIRECTIVE: $directive"
        $INJECT "$SESSION" "$directive" 2>/dev/null || true
    fi
}

# ---------------------------------------------------------------------------
# Main supervisor loop
# ---------------------------------------------------------------------------
while true; do
    CYCLE=$((CYCLE + 1))

    # -----------------------------------------------------------------------
    # Phase 1: Collect pod state (same as v2)
    # -----------------------------------------------------------------------
    POD_LOG=$(kubectl logs workload-pod-0 -n gpu-transport 2>/dev/null || echo "NO_PODS")

    BOLT_INIT=$(echo "$POD_LOG" | grep -c "\[BOLT\]" || echo 0)
    BOLT_WORKERS=$(echo "$POD_LOG" | grep -c "BOLT-WORKER.*started" || echo 0)
    BOLT_PEERS=$(echo "$POD_LOG" | grep -oP "peers=\K[0-9]+" | tail -1 || echo "?")
    BOLT_C0=$(echo "$POD_LOG" | grep -c "BOLT-C0" || echo 0)
    BOLT_DISPATCH=$(echo "$POD_LOG" | grep -c "BOLT-WORKER.*Dispatch" || echo 0)
    DIAG_F=$(echo "$POD_LOG" | grep -c "DIAG-F" || echo 0)
    PASSED=$(echo "$POD_LOG" | grep -oP "Passed:\s+\K[0-9]+" || echo 0)
    TIMEOUT=$(echo "$POD_LOG" | grep -c "timeout.*dispatch\|sender timeout" || echo 0)

    # -----------------------------------------------------------------------
    # Phase 2: Determine state (same as v2)
    # -----------------------------------------------------------------------
    STATE="UNKNOWN"
    DIRECTIVE=""

    if [ "$POD_LOG" = "NO_PODS" ]; then
        STATE="NO_PODS"
    elif [ "$BOLT_INIT" -eq 0 ]; then
        STATE="NO_BOLT"
        DIRECTIVE="Bolt not on pods. Rebuild with USE_BOLT=1 and deploy."
    elif [ "$BOLT_WORKERS" -eq 0 ]; then
        STATE="NO_WORKERS"
        DIRECTIVE="No Bolt workers. Call bolt_start_worker() after peers applied."
    elif [ "$BOLT_PEERS" = "0" ] || [ "$BOLT_PEERS" = "?" ]; then
        STATE="PEERS_MISSING"
        DIRECTIVE="Workers have peers=0. Add bolt_apply_peers() call in fabric_apply_remote() of runtime.cu."
    elif [ "$DIAG_F" -eq 0 ]; then
        STATE="BARRIER_WAIT"
    elif [ "$BOLT_C0" -eq 0 ] && [ "$TIMEOUT" -gt 0 ]; then
        STATE="C0_TIMEOUT"
        DIRECTIVE="DIAG-F passed but no BOLT-C0. Coordinator signal never fired. Check g_bolt_dispatch_signals is non-null and sender warps complete."
    elif [ "$BOLT_C0" -gt 0 ] && [ "$BOLT_DISPATCH" -eq 0 ]; then
        STATE="C0_NO_WORKER"
        DIRECTIVE="GPU signaled C0 but worker didnt dispatch. Check worker polls host_dispatch_signals and signal addresses match."
    elif [ "$BOLT_DISPATCH" -gt 0 ]; then
        STATE="DISPATCHING"
    fi

    if [ "$PASSED" -gt 0 ] && [ "$TIMEOUT" -eq 0 ]; then
        STATE="ALL_PASS"
    fi

    # -----------------------------------------------------------------------
    # Phase 3: Track state duration
    # -----------------------------------------------------------------------
    if [ "$STATE" = "$LAST_STATE" ]; then
        SAME_STATE_COUNT=$((SAME_STATE_COUNT + 1))
    else
        SAME_STATE_COUNT=1
        LAST_STATE="$STATE"
    fi

    log "Cycle $CYCLE: $STATE (${SAME_STATE_COUNT}x) | init=$BOLT_INIT workers=$BOLT_WORKERS peers=$BOLT_PEERS c0=$BOLT_C0 dispatch=$BOLT_DISPATCH diagF=$DIAG_F passed=$PASSED timeout=$TIMEOUT"

    # -----------------------------------------------------------------------
    # Phase 4: CUCo advisor for stuck states
    # -----------------------------------------------------------------------
    if [ "$SAME_STATE_COUNT" -ge "$STUCK_THRESHOLD" ] && [ "$STATE" != "ALL_PASS" ] && [ "$STATE" != "BARRIER_WAIT" ] && [ "$STATE" != "NO_PODS" ]; then
        log_cuco "State $STATE stuck for $SAME_STATE_COUNT cycles (>= $STUCK_THRESHOLD) — consulting CUCo advisor"

        HAS_TIMEOUT="false"
        if [ "$TIMEOUT" -gt 0 ]; then
            HAS_TIMEOUT="true"
        fi

        ADVISOR_JSON=$(run_cuco_advisor "$STATE" "$HAS_TIMEOUT" 2>/dev/null || echo "")

        if [ -n "$ADVISOR_JSON" ]; then
            # Log the full advisory
            ADVISORY_TEXT=$(python3 "$CUCO_ADVISOR" --state "$STATE" $([ "$HAS_TIMEOUT" = "true" ] && echo "--timeout") 2>/dev/null || echo "")
            if [ -n "$ADVISORY_TEXT" ]; then
                while IFS= read -r line; do
                    log "$line"
                done <<< "$ADVISORY_TEXT"
            fi

            # Extract untried suggestions
            SUGGESTION_LINES=$(get_untried_suggestion "$STATE" "$ADVISOR_JSON")
            FOUND_UNTRIED=false

            while IFS='|' read -r dim value desc; do
                [ -z "$dim" ] && continue

                if is_tried "$STATE" "$dim" "$value"; then
                    log_cuco "Already tried: $dim=$value — skipping"
                    continue
                fi

                # Found an untried suggestion
                FOUND_UNTRIED=true
                log_cuco "Suggesting untried alternative: $dim=$value"
                if [ -n "$desc" ]; then
                    log_cuco "  Description: $desc"
                fi

                mark_tried "$STATE" "$dim" "$value"

                # Override the directive with CUCo-guided advice
                DIRECTIVE="[CUCo] Stuck in $STATE for $SAME_STATE_COUNT cycles. Try changing dimension $dim to $value. $desc"
                break  # Only suggest one at a time
            done <<< "$SUGGESTION_LINES"

            if [ "$FOUND_UNTRIED" = false ]; then
                log_cuco "All suggestions for $STATE have been tried. Consider a full config change."
                # Suggest a named recommendation from the design space
                REC_NAME=$(echo "$ADVISOR_JSON" | python3 -c "
import sys, json
data = json.loads(sys.stdin.read())
rec = data.get('recommendation')
if rec:
    name = rec.get('name', '')
    cfg = rec.get('config', {})
    desc = rec.get('description', '')
    parts = ' '.join(f'{k}={v}' for k, v in cfg.items())
    print(f'{name}: {parts} ({desc})')
" 2>/dev/null || echo "")
                if [ -n "$REC_NAME" ]; then
                    log_cuco "Recommending full config switch: $REC_NAME"
                    DIRECTIVE="[CUCo] All individual suggestions tried. Switch to recommended config: $REC_NAME"
                fi
            fi
        else
            log_cuco "Advisor returned no results for state $STATE"
        fi
    fi

    # -----------------------------------------------------------------------
    # Phase 5: Pre-deploy gate for build/deploy directives
    # -----------------------------------------------------------------------
    # Check if the directive involves a build/deploy and there is a candidate .cu
    GATE_PASSED=true
    if [ -n "$DIRECTIVE" ]; then
        # Look for a recently modified .cu candidate in the kernel source
        KERNEL_DIR="<HOME>/<project>"
        if echo "$DIRECTIVE" | grep -qiE "rebuild|deploy|build|compile|USE_BOLT"; then
            CANDIDATE_CU="${KERNEL_DIR}/internode.cu"
            if [ -f "$CANDIDATE_CU" ]; then
                log_cuco "Directive involves build — running pre-deploy gate"
                if ! run_pre_deploy_gate "$CANDIDATE_CU"; then
                    GATE_PASSED=false
                    log_cuco "Pre-deploy gate BLOCKED directive: $DIRECTIVE"
                    DIRECTIVE=""  # Clear directive — don't send a build command for broken code
                fi
            fi
        fi
    fi

    # -----------------------------------------------------------------------
    # Phase 6: Send directive (deduplicated, respects dry-run)
    # -----------------------------------------------------------------------
    if [ -n "$DIRECTIVE" ] && [ "$DIRECTIVE" != "$LAST_DIRECTIVE" ]; then
        send_directive "$DIRECTIVE"
        LAST_DIRECTIVE="$DIRECTIVE"
    fi

    sleep "$INTERVAL"
done
