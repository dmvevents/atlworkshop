#!/bin/bash
# efa-traffic-monitor.sh — Continuous EFA HW counter monitor
# Checks actual wire traffic (tx_pkts, rx_pkts) on pods every N seconds.
# Detects: zero traffic (fi_writemsg OK but no packets), one-way traffic,
# and measures throughput.
#
# Usage:
#   ./efa-traffic-monitor.sh [namespace] [pod-prefix] [interval]
#   ./efa-traffic-monitor.sh gpu-transport workload-pod 30

set -euo pipefail

NS="${1:-gpu-transport}"
POD_PREFIX="${2:-workload-pod}"
INTERVAL="${3:-30}"
LOG="<HPC_STACK_ROOT>/supervisor/logs/efa-traffic.log"
mkdir -p "$(dirname "$LOG")"

log() { echo "[$(date +%H:%M:%S)] $*" | tee -a "$LOG"; }

# Read counters from a pod via `rdma stat` (sysfs hw_counters doesn't exist on HyperPod).
# Returns: tx_pkts rx_pkts tx_bytes rx_bytes (summed across all EFA devices)
read_counters() {
    local pod="$1"
    kubectl exec "$pod" -n "$NS" -- bash -c '
        tx_p=0; rx_p=0; tx_b=0; rx_b=0
        while read line; do
            tp=$(echo "$line" | grep -oP "tx_pkts \K\d+" || echo 0)
            rp=$(echo "$line" | grep -oP "rx_pkts \K\d+" || echo 0)
            tb=$(echo "$line" | grep -oP "tx_bytes \K\d+" || echo 0)
            rb=$(echo "$line" | grep -oP "rx_bytes \K\d+" || echo 0)
            tx_p=$((tx_p + tp)); rx_p=$((rx_p + rp))
            tx_b=$((tx_b + tb)); rx_b=$((rx_b + rb))
        done < <(rdma stat 2>/dev/null)
        echo "$tx_p $rx_p $tx_b $rx_b"
    ' 2>/dev/null || echo "0 0 0 0"
}

# Per-device breakdown via `rdma stat`
read_per_device() {
    local pod="$1"
    kubectl exec "$pod" -n "$NS" -- bash -c '
        rdma stat 2>/dev/null | while read line; do
            dev=$(echo "$line" | grep -oP "link \K\S+")
            tp=$(echo "$line" | grep -oP "tx_pkts \K\d+")
            rp=$(echo "$line" | grep -oP "rx_pkts \K\d+")
            wr=$(echo "$line" | grep -oP "rdma_write_bytes \K\d+")
            retrans=$(echo "$line" | grep -oP "retrans_pkts \K\d+")
            [ "$tp" -gt 1000 ] 2>/dev/null && printf "  %-18s tx=%-12s rx=%-12s write_GB=%-6s retrans=%s\n" \
                "$dev" "$tp" "$rp" "$((wr/1073741824))" "$retrans"
        done
    ' 2>/dev/null
}

log "EFA Traffic Monitor started: ns=$NS prefix=$POD_PREFIX interval=${INTERVAL}s"

# Previous counters for delta calculation
PREV_TX0=0; PREV_RX0=0; PREV_TB0=0; PREV_RB0=0
PREV_TX1=0; PREV_RX1=0; PREV_TB1=0; PREV_RB1=0
CYCLE=0

while true; do
    CYCLE=$((CYCLE + 1))

    # Check pods exist
    POD0="${POD_PREFIX}-0"
    POD1="${POD_PREFIX}-1"
    if ! kubectl get pod "$POD0" -n "$NS" &>/dev/null; then
        log "Cycle $CYCLE: pods not ready"
        sleep "$INTERVAL"
        continue
    fi

    # Read counters
    read -r TX0 RX0 TB0 RB0 <<< "$(read_counters "$POD0")"
    read -r TX1 RX1 TB1 RB1 <<< "$(read_counters "$POD1")"

    # Calculate deltas
    DTX0=$((TX0 - PREV_TX0)); DRX0=$((RX0 - PREV_RX0))
    DTX1=$((TX1 - PREV_TX1)); DRX1=$((RX1 - PREV_RX1))
    DTB0=$((TB0 - PREV_TB0)); DRB0=$((RB0 - PREV_RB0))
    DTB1=$((TB1 - PREV_TB1)); DRB1=$((RB1 - PREV_RB1))

    # Throughput (MB/s)
    if [ "$INTERVAL" -gt 0 ]; then
        TP0=$((DTB0 / INTERVAL / 1024 / 1024)) 2>/dev/null || TP0=0
        TP1=$((DTB1 / INTERVAL / 1024 / 1024)) 2>/dev/null || TP1=0
    else
        TP0=0; TP1=0
    fi

    # Detect anomalies
    STATUS="OK"
    if [ "$TX0" -eq 0 ] && [ "$TX1" -eq 0 ]; then
        STATUS="NO_TRAFFIC"
    elif [ "$TX0" -gt 0 ] && [ "$TX1" -eq 0 ]; then
        STATUS="ONE_WAY(pod0→pod1)"
    elif [ "$TX0" -eq 0 ] && [ "$TX1" -gt 0 ]; then
        STATUS="ONE_WAY(pod1→pod0)"
    elif [ "$DTX0" -eq 0 ] && [ "$DTX1" -eq 0 ] && [ "$CYCLE" -gt 1 ]; then
        STATUS="STALLED"
    fi

    log "Cycle $CYCLE: $STATUS"
    log "  pod-0: tx_pkts=$TX0(+$DTX0) rx_pkts=$RX0(+$DRX0) tx_MB/s=$TP0"
    log "  pod-1: tx_pkts=$TX1(+$DTX1) rx_pkts=$RX1(+$DRX1) tx_MB/s=$TP1"

    # Log per-device breakdown if traffic exists
    if [ "$TX0" -gt 0 ] || [ "$TX1" -gt 0 ]; then
        if [ "$CYCLE" -le 3 ] || [ $((CYCLE % 10)) -eq 0 ]; then
            log "  --- pod-0 per-device ---"
            read_per_device "$POD0" | while read line; do log "  $line"; done
            log "  --- pod-1 per-device ---"
            read_per_device "$POD1" | while read line; do log "  $line"; done
        fi
    fi

    # Save for next delta
    PREV_TX0=$TX0; PREV_RX0=$RX0; PREV_TB0=$TB0; PREV_RB0=$RB0
    PREV_TX1=$TX1; PREV_RX1=$RX1; PREV_TB1=$TB1; PREV_RB1=$RB1

    sleep "$INTERVAL"
done
