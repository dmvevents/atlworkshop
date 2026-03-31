#!/bin/bash
# =============================================================================
# 00-preflight.sh - Workshop Preflight Checks
# Mastering Agentic Coding & GPUs Workshop
# =============================================================================
# Verifies all prerequisites before running workshop demos:
#   - kubectl access and cluster connectivity
#   - GPU nodes available (nvidia.com/gpu resources)
#   - EFA device plugin running
#   - Docker/containerd available
#   - Required CLI tools (claude, helm, aws, kubectl)
#   - Namespace creation for workshop
# =============================================================================
set -euo pipefail

# ---------------------------------------------------------------------------
# Color helpers
# ---------------------------------------------------------------------------
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m' # No Color

PASS="${GREEN}[PASS]${NC}"
FAIL="${RED}[FAIL]${NC}"
WARN="${YELLOW}[WARN]${NC}"
INFO="${CYAN}[INFO]${NC}"

WORKSHOP_NS="${WORKSHOP_NS:-workshop-agentic}"
ERRORS=0

header() {
    echo ""
    echo -e "${BOLD}============================================${NC}"
    echo -e "${BOLD}  Mastering Agentic Coding & GPUs${NC}"
    echo -e "${BOLD}  Preflight Checks${NC}"
    echo -e "${BOLD}============================================${NC}"
    echo ""
}

check() {
    local description="$1"
    shift
    if "$@" >/dev/null 2>&1; then
        echo -e "  ${PASS} ${description}"
        return 0
    else
        echo -e "  ${FAIL} ${description}"
        ERRORS=$((ERRORS + 1))
        return 1
    fi
}

check_version() {
    local tool="$1"
    local version
    version=$("$tool" --version 2>/dev/null | head -1) || version="not found"
    echo -e "         ${CYAN}${version}${NC}"
}

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
header

# ---- Section 1: CLI Tools ------------------------------------------------
echo -e "${BOLD}1. Required CLI Tools${NC}"
echo -e "   -------------------"

for tool in kubectl helm aws claude docker; do
    if command -v "$tool" >/dev/null 2>&1; then
        echo -e "  ${PASS} ${tool}"
        check_version "$tool"
    else
        echo -e "  ${FAIL} ${tool} -- not found in PATH"
        ERRORS=$((ERRORS + 1))
    fi
done

# Optional tools
for tool in jq curl git python3; do
    if command -v "$tool" >/dev/null 2>&1; then
        echo -e "  ${PASS} ${tool} (optional)"
    else
        echo -e "  ${WARN} ${tool} (optional, not found)"
    fi
done

# ---- Section 2: Cluster Connectivity -------------------------------------
echo ""
echo -e "${BOLD}2. Kubernetes Cluster Connectivity${NC}"
echo -e "   --------------------------------"

if kubectl cluster-info >/dev/null 2>&1; then
    CLUSTER_NAME=$(kubectl config current-context 2>/dev/null || echo "unknown")
    echo -e "  ${PASS} kubectl can reach the API server"
    echo -e "         ${CYAN}Context: ${CLUSTER_NAME}${NC}"
else
    echo -e "  ${FAIL} kubectl cannot reach the API server"
    echo -e "         Run: aws eks update-kubeconfig --name <cluster> --region <region>"
    ERRORS=$((ERRORS + 1))
fi

NODE_COUNT=$(kubectl get nodes --no-headers 2>/dev/null | wc -l || echo "0")
if [[ "$NODE_COUNT" -gt 0 ]]; then
    echo -e "  ${PASS} Cluster has ${NODE_COUNT} node(s)"
else
    echo -e "  ${FAIL} No nodes found in cluster"
    ERRORS=$((ERRORS + 1))
fi

# ---- Section 3: GPU Resources --------------------------------------------
echo ""
echo -e "${BOLD}3. GPU Resources${NC}"
echo -e "   -------------"

GPU_NODES=$(kubectl get nodes -o json 2>/dev/null \
    | python3 -c "
import sys, json
data = json.load(sys.stdin)
count = 0
for node in data.get('items', []):
    alloc = node.get('status', {}).get('allocatable', {})
    gpus = int(alloc.get('nvidia.com/gpu', '0'))
    if gpus > 0:
        name = node['metadata']['name']
        print(f'         GPU node: {name} ({gpus} GPUs)')
        count += gpus
print(f'__TOTAL__:{count}')
" 2>/dev/null) || GPU_NODES="__TOTAL__:0"

TOTAL_GPUS=$(echo "$GPU_NODES" | grep '__TOTAL__' | cut -d: -f2)
GPU_NODE_LINES=$(echo "$GPU_NODES" | grep -v '__TOTAL__' || true)

if [[ "$TOTAL_GPUS" -gt 0 ]]; then
    echo -e "  ${PASS} Total GPUs available: ${TOTAL_GPUS}"
    if [[ -n "$GPU_NODE_LINES" ]]; then
        echo -e "${CYAN}${GPU_NODE_LINES}${NC}"
    fi
else
    echo -e "  ${FAIL} No GPU resources found (nvidia.com/gpu)"
    echo -e "         Ensure NVIDIA device plugin is installed"
    ERRORS=$((ERRORS + 1))
fi

# Check NVIDIA device plugin DaemonSet
if kubectl get daemonset -A -o json 2>/dev/null \
    | python3 -c "
import sys, json
data = json.load(sys.stdin)
for ds in data.get('items', []):
    name = ds['metadata']['name']
    if 'nvidia' in name.lower() and 'device' in name.lower():
        ready = ds.get('status', {}).get('numberReady', 0)
        desired = ds.get('status', {}).get('desiredNumberScheduled', 0)
        print(f'{name}: {ready}/{desired}')
        sys.exit(0)
sys.exit(1)
" 2>/dev/null; then
    echo -e "  ${PASS} NVIDIA device plugin DaemonSet is running"
else
    echo -e "  ${WARN} NVIDIA device plugin DaemonSet not detected"
fi

# ---- Section 4: EFA Device Plugin ----------------------------------------
echo ""
echo -e "${BOLD}4. EFA (Elastic Fabric Adapter)${NC}"
echo -e "   ----------------------------"

EFA_DS=$(kubectl get daemonset -A -o json 2>/dev/null \
    | python3 -c "
import sys, json
data = json.load(sys.stdin)
for ds in data.get('items', []):
    name = ds['metadata']['name']
    ns = ds['metadata']['namespace']
    if 'efa' in name.lower():
        ready = ds.get('status', {}).get('numberReady', 0)
        desired = ds.get('status', {}).get('desiredNumberScheduled', 0)
        print(f'{ns}/{name}: {ready}/{desired}')
        sys.exit(0)
sys.exit(1)
" 2>/dev/null) || true

if [[ -n "$EFA_DS" ]]; then
    echo -e "  ${PASS} EFA device plugin: ${EFA_DS}"
else
    echo -e "  ${WARN} EFA device plugin DaemonSet not detected"
    echo -e "         EFA is optional -- required only for multi-node GPU demos"
fi

# Check for vpc.amazonaws.com/efa resources on nodes
EFA_CAPABLE=$(kubectl get nodes -o json 2>/dev/null \
    | python3 -c "
import sys, json
data = json.load(sys.stdin)
count = 0
for node in data.get('items', []):
    alloc = node.get('status', {}).get('allocatable', {})
    efa = int(alloc.get('vpc.amazonaws.com/efa', '0'))
    if efa > 0:
        count += 1
print(count)
" 2>/dev/null) || EFA_CAPABLE="0"

if [[ "$EFA_CAPABLE" -gt 0 ]]; then
    echo -e "  ${PASS} ${EFA_CAPABLE} node(s) with EFA adapters"
else
    echo -e "  ${WARN} No nodes advertise vpc.amazonaws.com/efa"
fi

# ---- Section 5: Container Runtime ----------------------------------------
echo ""
echo -e "${BOLD}5. Container Runtime${NC}"
echo -e "   -----------------"

if command -v docker >/dev/null 2>&1 && docker info >/dev/null 2>&1; then
    echo -e "  ${PASS} Docker daemon is running"
elif command -v nerdctl >/dev/null 2>&1; then
    echo -e "  ${PASS} nerdctl available (containerd)"
elif command -v crictl >/dev/null 2>&1; then
    echo -e "  ${PASS} crictl available (CRI-compatible runtime)"
else
    echo -e "  ${WARN} No local container CLI detected (docker/nerdctl/crictl)"
    echo -e "         Not required if building images remotely"
fi

# ---- Section 6: Workshop Namespace ---------------------------------------
echo ""
echo -e "${BOLD}6. Workshop Namespace${NC}"
echo -e "   ------------------"

if kubectl get namespace "$WORKSHOP_NS" >/dev/null 2>&1; then
    echo -e "  ${PASS} Namespace '${WORKSHOP_NS}' already exists"
else
    echo -e "  ${INFO} Creating namespace '${WORKSHOP_NS}'..."
    if kubectl create namespace "$WORKSHOP_NS" 2>/dev/null; then
        echo -e "  ${PASS} Namespace '${WORKSHOP_NS}' created"
    else
        echo -e "  ${FAIL} Failed to create namespace '${WORKSHOP_NS}'"
        ERRORS=$((ERRORS + 1))
    fi
fi

# Label the namespace for easy cleanup
kubectl label namespace "$WORKSHOP_NS" \
    workshop=mastering-agentic-coding \
    managed-by=workshop-scripts \
    --overwrite >/dev/null 2>&1 || true

# ---- Section 7: AWS Identity (optional) ----------------------------------
echo ""
echo -e "${BOLD}7. AWS Identity${NC}"
echo -e "   ------------"

if aws sts get-caller-identity >/dev/null 2>&1; then
    ACCOUNT_ID=$(aws sts get-caller-identity --query 'Account' --output text 2>/dev/null)
    REGION=$(aws configure get region 2>/dev/null || echo "not set")
    echo -e "  ${PASS} AWS credentials valid"
    echo -e "         ${CYAN}Account: ${ACCOUNT_ID}${NC}"
    echo -e "         ${CYAN}Region:  ${REGION}${NC}"
else
    echo -e "  ${WARN} AWS credentials not configured or expired"
    echo -e "         Some demos may require valid AWS credentials"
fi

# ---- Summary -------------------------------------------------------------
echo ""
echo -e "${BOLD}============================================${NC}"
if [[ "$ERRORS" -eq 0 ]]; then
    echo -e "${GREEN}${BOLD}  All preflight checks passed!${NC}"
    echo -e "  Workshop namespace: ${WORKSHOP_NS}"
    echo -e "  You are ready to run the demos."
else
    echo -e "${RED}${BOLD}  ${ERRORS} check(s) failed.${NC}"
    echo -e "  Please resolve the issues above before proceeding."
fi
echo -e "${BOLD}============================================${NC}"
echo ""

exit "$ERRORS"
