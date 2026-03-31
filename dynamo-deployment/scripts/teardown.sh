#!/bin/bash
set -euo pipefail

# =============================================================================
# teardown.sh — Remove all Dynamo deployments from the workshop namespace
# =============================================================================

NAMESPACE="${NAMESPACE:-workshop}"

echo "Removing Dynamo deployments from namespace '$NAMESPACE'..."

kubectl delete dynamographdeployment --all -n "$NAMESPACE" 2>/dev/null || true
kubectl delete secret hf-token-secret -n "$NAMESPACE" 2>/dev/null || true

echo "Waiting for pods to terminate..."
sleep 5
kubectl get pods -n "$NAMESPACE" --no-headers 2>/dev/null || echo "No pods remaining"

echo "Done. Namespace '$NAMESPACE' still exists (delete manually if needed)."
