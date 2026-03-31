#!/bin/bash
set -euo pipefail

# =============================================================================
# Workshop Teardown - Remove all workshop resources
# =============================================================================

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo -e "${RED}=== Workshop Teardown ===${NC}"
echo "This will remove ALL workshop resources from the cluster."
echo ""
read -p "Are you sure? (yes/no): " CONFIRM
if [ "$CONFIRM" != "yes" ]; then
    echo "Aborted."
    exit 0
fi

NAMESPACE="workshop"
step() { echo -e "${GREEN}[TEARDOWN]${NC} $1"; }

step "Removing Dynamo deployments..."
kubectl delete dynamographdeployment --all -n "$NAMESPACE" 2>/dev/null || true
kubectl delete deployment dynamo-frontend dynamo-prefill dynamo-decode -n "$NAMESPACE" 2>/dev/null || true
kubectl delete service dynamo-frontend-svc -n "$NAMESPACE" 2>/dev/null || true
kubectl delete configmap dynamo-config -n "$NAMESPACE" 2>/dev/null || true

step "Removing OpenClaw deployments..."
kubectl delete deployment openclaw-gateway -n "$NAMESPACE" 2>/dev/null || true
kubectl delete service openclaw-svc -n "$NAMESPACE" 2>/dev/null || true
kubectl delete configmap openclaw-config -n "$NAMESPACE" 2>/dev/null || true

step "Removing test pods..."
kubectl delete pod gpu-test efa-test -n "$NAMESPACE" 2>/dev/null || true

step "Removing workshop namespace..."
kubectl delete namespace "$NAMESPACE" 2>/dev/null || true

echo ""
step "Teardown complete."
echo -e "${YELLOW}Verify with: kubectl get all --all-namespaces | grep workshop${NC}"
