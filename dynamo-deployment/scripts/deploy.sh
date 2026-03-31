#!/bin/bash
set -euo pipefail

# =============================================================================
# deploy.sh — Deploy NVIDIA Dynamo with a coding model on EKS
#
# This script automates the full deployment:
#   1. Verify prerequisites (kubectl, GPU nodes, Dynamo operator)
#   2. Create namespace
#   3. Deploy the coding model via DynamoGraphDeployment
#   4. Wait for pods to be ready
#   5. Run a smoke test
#
# Usage:
#   ./deploy.sh                          # Deploy Qwen2.5-Coder-7B (default)
#   ./deploy.sh --model large            # Deploy 32B model with TP=2
#   ./deploy.sh --namespace my-ns        # Custom namespace
#   ./deploy.sh --dry-run                # Show what would be deployed
# =============================================================================

GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

NAMESPACE="${NAMESPACE:-workshop}"
MODEL="${1:-default}"
DRY_RUN=""
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
MANIFEST_DIR="$SCRIPT_DIR/../manifests"

# Parse args
for arg in "$@"; do
    case $arg in
        --model) MODEL="$2"; shift 2 ;;
        --namespace) NAMESPACE="$2"; shift 2 ;;
        --dry-run) DRY_RUN="--dry-run=client"; shift ;;
        large|32b) MODEL="large" ;;
    esac
done

step() { echo -e "${GREEN}[STEP]${NC} $1"; }
warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
fail() { echo -e "${RED}[FAIL]${NC} $1"; exit 1; }
info() { echo -e "${CYAN}[INFO]${NC} $1"; }

echo -e "${CYAN}=== NVIDIA Dynamo Deployment ===${NC}"
echo "  Model:     $MODEL"
echo "  Namespace: $NAMESPACE"
echo ""

# --- Step 1: Prerequisites ---
step "Checking prerequisites..."

kubectl cluster-info > /dev/null 2>&1 || fail "kubectl not connected to cluster"
echo "  kubectl: connected"

GPU_NODES=$(kubectl get nodes -o json | jq '[.items[] | select(.status.allocatable["nvidia.com/gpu"] != null and .status.allocatable["nvidia.com/gpu"] != "0")] | length')
if [ "$GPU_NODES" -eq 0 ]; then
    fail "No GPU nodes found in cluster"
fi
echo "  GPU nodes: $GPU_NODES"

DYNAMO_OPERATOR=$(kubectl get pods -n default 2>/dev/null | grep -c "dynamo.*controller.*Running" || true)
if [ "$DYNAMO_OPERATOR" -eq 0 ]; then
    warn "Dynamo operator not found. Install with:"
    echo "  helm install dynamo-platform oci://nvcr.io/nvidia/ai-dynamo/dynamo-platform --version 0.7.0"
    fail "Dynamo operator required"
fi
echo "  Dynamo operator: running"

ETCD_RUNNING=$(kubectl get pods -n default 2>/dev/null | grep -c "etcd.*Running" || true)
NATS_RUNNING=$(kubectl get pods -n default 2>/dev/null | grep -c "nats.*Running" || true)
echo "  etcd: $ETCD_RUNNING running"
echo "  NATS: $NATS_RUNNING running"
echo ""

# --- Step 2: Create namespace ---
step "Creating namespace '$NAMESPACE'..."
kubectl create namespace "$NAMESPACE" --dry-run=client -o yaml | kubectl apply $DRY_RUN -f -
echo ""

# --- Step 3: Deploy model ---
if [ "$MODEL" = "large" ] || [ "$MODEL" = "32b" ]; then
    step "Deploying large coding model (32B, TP=2)..."
    MANIFEST="$MANIFEST_DIR/04-dynamo-large-model.yaml"
    # Check for HF token
    if ! kubectl get secret hf-token-secret -n "$NAMESPACE" > /dev/null 2>&1; then
        warn "hf-token-secret not found. Large models may need it."
        echo "  Create with: kubectl create secret generic hf-token-secret -n $NAMESPACE --from-literal=HUGGING_FACE_HUB_TOKEN=<TOKEN>"
    fi
else
    step "Deploying Qwen2.5-Coder-7B-Instruct..."
    MANIFEST="$MANIFEST_DIR/03-dynamo-coding-model.yaml"
fi

kubectl apply $DRY_RUN -f "$MANIFEST"
echo ""

if [ -n "$DRY_RUN" ]; then
    info "Dry run complete. No resources created."
    exit 0
fi

# --- Step 4: Wait for pods ---
step "Waiting for pods to be ready (up to 5 minutes)..."
echo "  Watching pods in namespace '$NAMESPACE'..."

TIMEOUT=300
ELAPSED=0
while [ $ELAPSED -lt $TIMEOUT ]; do
    READY=$(kubectl get pods -n "$NAMESPACE" --no-headers 2>/dev/null | grep -c "1/1.*Running" || true)
    TOTAL=$(kubectl get pods -n "$NAMESPACE" --no-headers 2>/dev/null | grep -v "Terminating" | wc -l)
    echo -ne "\r  Pods: $READY/$TOTAL ready (${ELAPSED}s elapsed)    "

    if [ "$READY" -ge 2 ] && [ "$TOTAL" -ge 2 ]; then
        echo ""
        echo -e "  ${GREEN}All pods ready!${NC}"
        break
    fi

    sleep 10
    ELAPSED=$((ELAPSED + 10))
done

if [ $ELAPSED -ge $TIMEOUT ]; then
    warn "Timeout waiting for pods. Check status:"
    kubectl get pods -n "$NAMESPACE"
    exit 1
fi
echo ""

# --- Step 5: Smoke test ---
step "Running smoke test..."
FRONTEND_POD=$(kubectl get pods -n "$NAMESPACE" --no-headers | grep "frontend.*Running" | head -1 | awk '{print $1}')

if [ -z "$FRONTEND_POD" ]; then
    warn "No frontend pod found. Skipping smoke test."
    exit 0
fi

# Test via kubectl exec (no port-forward needed)
MODELS=$(kubectl exec -n "$NAMESPACE" "$FRONTEND_POD" -- curl -s http://localhost:8000/v1/models 2>/dev/null)
MODEL_ID=$(echo "$MODELS" | jq -r '.data[0].id' 2>/dev/null)

if [ -n "$MODEL_ID" ] && [ "$MODEL_ID" != "null" ]; then
    echo -e "  Model available: ${GREEN}$MODEL_ID${NC}"

    # Test inference
    ANSWER=$(kubectl exec -n "$NAMESPACE" "$FRONTEND_POD" -- curl -s http://localhost:8000/v1/chat/completions \
        -H "Content-Type: application/json" \
        -d '{"model":"'"$MODEL_ID"'","messages":[{"role":"user","content":"What is 7*8? Just the number."}],"max_tokens":5,"temperature":0}' 2>/dev/null | jq -r '.choices[0].message.content' 2>/dev/null)
    echo -e "  Inference test (7*8): ${GREEN}$ANSWER${NC}"
else
    warn "Model not loaded yet. May still be downloading weights."
    echo "  Monitor with: kubectl logs -n $NAMESPACE $FRONTEND_POD -f"
fi

echo ""
echo -e "${GREEN}=== Deployment Complete ===${NC}"
echo ""
echo "Access the model:"
echo "  kubectl port-forward -n $NAMESPACE svc/qwen-coder-frontend 8000:8000"
echo "  curl http://localhost:8000/v1/chat/completions \\"
echo "    -H 'Content-Type: application/json' \\"
echo "    -d '{\"model\":\"$MODEL_ID\",\"messages\":[{\"role\":\"user\",\"content\":\"Hello\"}]}'"
